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

BESTBUY_CLEARANCE_URL = "https://www.bestbuy.ca/en-ca/collection/clearance-products/113065"


@dataclass
class Product:
    sku: str
    name: str
    price: Optional[float]
    regular_price: Optional[float]
    url: Optional[str]


class ScrapingError(Exception):
    """Raised when scraping fails."""


def fetch_page(url: str, timeout: int = 40, max_retries: int = 3) -> str:
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
            return response.text
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


def _extract_json_payload(html: str) -> Any:
    soup = BeautifulSoup(html, "html.parser")
    data_script = soup.find("script", id="__NEXT_DATA__")
    if data_script and data_script.string:
        return json.loads(data_script.string)

    for script in soup.find_all("script"):
        if not script.string:
            continue
        if "__NEXT_DATA__" in script.string:
            match = re.search(r"__NEXT_DATA__\s*=\s*(\{.*?\})\s*;", script.string, re.DOTALL)
            if match:
                return json.loads(match.group(1))

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


def scrape_products(url: str = BESTBUY_CLEARANCE_URL) -> List[Product]:
    html = fetch_page(url)
    payload = _extract_json_payload(html)
    product_entries = _search_for_products(payload)
    if not product_entries:
        raise ScrapingError("Could not find any products in the page payload.")

    return [_build_product(entry) for entry in product_entries]


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
        default=BESTBUY_CLEARANCE_URL,
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
