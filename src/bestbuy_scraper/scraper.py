import argparse
import json
import pathlib
import re
import time
import random
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional

import requests
from bs4 import BeautifulSoup

from .config import BESTBUY_SEED_URL

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}


@dataclass
class Product:
    sku: str
    name: str
    price: Optional[float]
    regular_price: Optional[float]
    url: Optional[str]


class ScrapingError(Exception):
    pass


def fetch_page(url: str, timeout: int = 40, max_retries: int = 3) -> tuple[str, str]:
    """
    Fetch a BestBuy page with basic retry and backoff.

    - Timeout augmenté (40s au lieu de 20s).
    - max_retries tentatives en cas de ReadTimeout ou erreur réseau.
    - Petits sleeps random entre les tentatives pour éviter de spammer.
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[fetch_page] GET {url} (attempt {attempt}/{max_retries}, timeout={timeout}s)")
            response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            response.raise_for_status()
            return response.text, response.url
        except requests.exceptions.ReadTimeout as e:
            print(f"[fetch_page][WARN] ReadTimeout on {url} (attempt {attempt}/{max_retries}): {e}")
            last_error = e
        except requests.RequestException as e:
            # inclut SSLError, ConnectionError, etc.
            print(f"[fetch_page][WARN] RequestException on {url} (attempt {attempt}/{max_retries}): {e}")
            last_error = e

        # backoff entre les tentatives
        sleep_s = random.uniform(3, 7)
        print(f"[fetch_page] Sleeping {sleep_s:.1f}s before retry...")
        time.sleep(sleep_s)

    # Si on arrive ici, toutes les tentatives ont échoué
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts") from last_error


def _extract_json_payload(html: str):
    """
    Essaie d'extraire le payload JSON BestBuy depuis la page.
    1. Tente d'abord de trouver un <script> contenant un JSON d'état.
    2. Si rien n'est trouvé, loggue un extrait du HTML et lève ScrapingError.

    NOTE : on ajoute ensuite un fallback pour parser directement les produits HTML
    dans scrape_products(), cette fonction reste focalisée sur l'extraction JSON.
    """
    # Exemple de patterns possibles (à adapter selon la structure actuelle)
    # On scanne tous les <script> et on cherche un JSON qui ressemble à un state.
    soup = BeautifulSoup(html, "html.parser")

    # Heuristique pour détecter une éventuelle page de blocage
    block_indicators = [
        "are you a robot",
        "unusual traffic",
        "access denied",
        "captcha",
        "bot detection",
    ]
    page_text_lower = soup.get_text(" ", strip=True).lower()
    if any(indicator in page_text_lower for indicator in block_indicators):
        snippet = html[:500].replace("\n", " ")
        print("[_extract_json_payload][WARN] Potential anti-bot page detected. HTML snippet:")
        print(snippet)
        raise ScrapingError("Potential anti-bot or access denied page detected.")

    scripts = soup.find_all("script")

    for script in scripts:
        if not script.string:
            continue
        text = script.string.strip()

        # Heuristique : éviter les scripts trop petits ou qui ne semblent pas être du JSON
        if len(text) < 50:
            continue

        # On ignore clairement les scripts qui commencent par "window.dataLayer", etc.
        if text.startswith("window") or text.startswith("!function"):
            continue

        # Essayer un parse JSON direct
        try:
            data = json.loads(text)
        except Exception:
            continue

        # Si on arrive ici, on a un JSON; on vérifie qu'il a l'air d'un payload de collection BestBuy
        # On ne connaît pas forcément la structure exacte, donc on reste générique.
        if isinstance(data, dict):
            # tu peux ajuster cette condition selon la structure actuelle de ton payload
            if "products" in data or "items" in data or "results" in data:
                return data

    # Si on n'a rien trouvé, on log un extrait du HTML pour debug
    snippet = html[:500].replace("\n", " ")
    print("[_extract_json_payload] Unable to locate JSON payload. HTML snippet:")
    print(snippet)
    raise ScrapingError("Unable to locate BestBuy page data payload.")


def _is_product_entry(item: Dict[str, Any]) -> bool:
    return "sku" in item and "name" in item


def _search_for_products(payload: Any) -> Optional[List[Dict[str, Any]]]:
    stack: List[Any] = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, list):
            if current and all(isinstance(entry, dict) for entry in current):
                if all(_is_product_entry(entry) for entry in current):
                    return current  # type: ignore[return-value]
            stack.extend(current)
        elif isinstance(current, dict):
            for value in current.values():
                if isinstance(value, list) and value and all(isinstance(entry, dict) for entry in value):
                    if all(_is_product_entry(entry) for entry in value):
                        return value  # type: ignore[return-value]
                stack.append(value)
    return None


def _parse_price(raw_value: Any) -> Optional[float]:
    if raw_value is None:
        return None
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def _build_product(entry: Dict[str, Any]) -> Product:
    price_fields = [
        "salePrice",
        "price",
        "priceWithEcoFee",
        "priceWithFees",
    ]
    regular_price_fields = [
        "regularPrice",
        "wasPrice",
    ]

    price = next((entry.get(field) for field in price_fields if entry.get(field) is not None), None)
    regular_price = next((entry.get(field) for field in regular_price_fields if entry.get(field) is not None), None)

    return Product(
        sku=str(entry.get("sku", "")),
        name=str(entry.get("name", "")).strip(),
        price=_parse_price(price),
        regular_price=_parse_price(regular_price),
        url=entry.get("url") or entry.get("canonicalUrl"),
    )


def _parse_products_from_payload(payload: Any) -> List[Product]:
    product_entries = _search_for_products(payload)
    if not product_entries:
        raise ScrapingError("Could not find any products in the page payload.")
    return [_build_product(entry) for entry in product_entries]


def _fallback_parse_products_from_html(html: str):
    """
    Fallback très simple si le JSON de BestBuy n'est pas trouvable.
    On parse directement les cartes produits dans le HTML.

    Stratégie:
    - Chercher tous les liens <a> dont le href contient '/en-ca/product/'.
    - Pour chaque lien, prendre le texte comme titre.
    - Récupérer un prix proche (élément suivant contenant un '$').

    NOTE: c'est volontairement générique, on n'essaie pas de recréer TOUT le JSON,
    juste de sortir une liste de produits utilisable pour un CSV.
    """
    soup = BeautifulSoup(html, "html.parser")
    products: List[Product] = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/en-ca/product/" not in href:
            continue

        full_url = href
        if full_url.startswith("/"):
            full_url = "https://www.bestbuy.ca" + full_url

        if full_url in seen_urls:
            continue

        title = a.get_text(strip=True)
        if not title:
            continue

        # Chercher un prix proche
        price_text = None
        # Regarder les noeuds après le lien
        for sibling in a.next_siblings:
            if getattr(sibling, "get_text", None):
                txt = sibling.get_text(strip=True)
            else:
                txt = str(sibling).strip()
            if "$" in txt:
                price_text = txt
                break

        price_value = None
        if price_text:
            match = re.search(r"\$\s*([0-9]+(?:\.[0-9]{2})?)", price_text)
            if match:
                try:
                    price_value = float(match.group(1))
                except ValueError:
                    price_value = None

        products.append(
            Product(
                sku="",
                name=title,
                price=price_value,
                regular_price=None,
                url=full_url,
            )
        )
        seen_urls.add(full_url)

    print(f"[_fallback_parse_products_from_html] Found {len(products)} products via HTML fallback.")
    return products


def scrape_products(url: str = BESTBUY_SEED_URL) -> List[Product]:
    """
    Scrape BestBuy clearance products depuis une URL de collection.

    1. Télécharge la page via fetch_page()
    2. Tente d'extraire le payload JSON via _extract_json_payload()
    3. Si ça échoue, utilise un fallback HTML simple pour extraire les produits.
    """
    print(f"[bestbuy] seedUrl={url}")
    html, final_url = fetch_page(url)
    if final_url != url:
        print(f"[bestbuy] finalUrl={final_url}")

    # 1) Essayer le chemin "officiel" JSON
    try:
        payload = _extract_json_payload(html)
        # Ici, garde ton parsing existant basé sur ce payload
        # (liste de produits, champs, etc.)
        products = _parse_products_from_payload(payload)
        return products

    except ScrapingError as e:
        print(f"[scrape_products] JSON payload not found, falling back to HTML parsing: {e}")
        # 2) Fallback HTML
        return _fallback_parse_products_from_html(html)


def save_products(products: Iterable[Product], output_path: pathlib.Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(product) for product in products]
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape BestBuy Canada clearance products.")
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("data/clearance_products.json"),
        help="Path to save the scraped JSON data.",
    )
    parser.add_argument(
        "--url",
        default=BESTBUY_SEED_URL,
        help="BestBuy clearance collection URL to scrape.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    products = scrape_products(args.url)
    save_products(products, args.output)
    print(f"Saved {len(products)} clearance products to {args.output}")


if __name__ == "__main__":
    main()
