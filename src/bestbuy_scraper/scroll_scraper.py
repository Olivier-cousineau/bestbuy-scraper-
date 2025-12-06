# src/bestbuy_scraper/scroll_scraper.py

import json
import time
import random
from typing import List, Dict

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


CLEARANCE_URL = "https://www.bestbuy.ca/en-ca/collection/clearance-products/113065"


def extract_products_from_html(html: str) -> List[Dict]:
    """
    Parse tous les produits depuis le HTML final (après scroll).
    Stratégie simple et robuste :
      - on cherche tous les <a> avec href contenant '/en-ca/product/'
      - on prend le texte comme titre
      - on essaie de trouver un prix proche
    """
    soup = BeautifulSoup(html, "html.parser")
    products = []
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

        # Chercher un prix proche dans les siblings ou parents
        price_text = None

        # 1) siblings après le lien
        for sibling in a.next_siblings:
            text = ""
            if hasattr(sibling, "get_text"):
                text = sibling.get_text(strip=True)
            else:
                text = str(sibling).strip()
            if "$" in text:
                price_text = text
                break

        # 2) si rien trouvé, essayer un parent
        if not price_text:
            parent = a.parent
            for _ in range(3):  # remonter maximum 3 niveaux
                if not parent:
                    break
                text = parent.get_text(strip=True)
                # heuristique très simple pour un prix
                if "$" in text:
                    # on prend la première occurence contenant $
                    for token in text.split():
                        if "$" in token:
                            price_text = token
                            break
                if price_text:
                    break
                parent = parent.parent if hasattr(parent, "parent") else None

        products.append(
            {
                "title": title,
                "url": full_url,
                "price_raw": price_text,
            }
        )
        seen_urls.add(full_url)

    print(f"[extract_products_from_html] Found {len(products)} products.")
    return products


def scroll_clearance_page(max_scrolls: int = 60, pause_sec: float = 1.5) -> str:
    """
    Ouvre la page clearance BestBuy et scrolle jusqu'à ce que
    plus rien ne se charge (ou jusqu'à max_scrolls).
    Retourne le HTML complet de la page à la fin.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )
        page = context.new_page()
        print(f"[scroll_clearance_page] Opening {CLEARANCE_URL}")
        page.goto(CLEARANCE_URL, wait_until="domcontentloaded", timeout=60000)

        # Attendre le premier rendu
        page.wait_for_timeout(3000)

        last_height = page.evaluate("document.body.scrollHeight")
        same_height_count = 0

        for i in range(max_scrolls):
            print(f"[scroll_clearance_page] Scroll {i+1}/{max_scrolls}")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            # petit temps d'attente pour laisser le JS charger les nouveaux produits
            sleep_time = pause_sec + random.uniform(0.2, 0.8)
            page.wait_for_timeout(int(sleep_time * 1000))

            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                same_height_count += 1
                print(
                    f"[scroll_clearance_page] No new content detected (same height x{same_height_count})."
                )
                # si la hauteur n'a pas changé sur plusieurs scrolls, on considère que c'est fini
                if same_height_count >= 3:
                    print("[scroll_clearance_page] Reached bottom, stopping scroll.")
                    break
            else:
                same_height_count = 0
                last_height = new_height

        html = page.content()
        browser.close()
        return html


def scrape_bestbuy_clearance() -> List[Dict]:
    """
    Pipeline complet :
      1) Scroll la page BestBuy clearance
      2) Extract tous les produits du HTML complet
    """
    html = scroll_clearance_page()
    products = extract_products_from_html(html)
    return products


def main():
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description="Scrape BestBuy.ca clearance products via Playwright scroll."
    )
    parser.add_argument(
        "--output",
        "-o",
        default="data/clearance_products_full.json",
        help="Output JSON file path.",
    )
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    products = scrape_bestbuy_clearance()

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(products)} clearance products to {args.output}")


if __name__ == "__main__":
    main()
