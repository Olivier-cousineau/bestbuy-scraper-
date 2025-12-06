# src/bestbuy_scraper/scroll_scraper.py

import json
import time
import random
from typing import List, Dict

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


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


def scroll_clearance_page(max_scrolls: int = 60, pause_sec: float = 1.5, max_show_more_clicks: int = 30) -> str:
    """
    Ouvre la page clearance BestBuy et :
      1) scrolle un peu pour initialiser la page
      2) clique sur le bouton "Show more" tant qu'il existe (et jusqu'à max_show_more_clicks)
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

        # Petit délai pour laisser la page initiale se charger
        page.wait_for_timeout(3000)

        # 1) Scroll léger pour déclencher les premiers loads
        last_height = page.evaluate("document.body.scrollHeight")
        for i in range(5):
            print(f"[scroll_clearance_page] Initial scroll {i+1}/5")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            sleep_time = pause_sec + random.uniform(0.2, 0.8)
            page.wait_for_timeout(int(sleep_time * 1000))
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        # 2) Clique sur "Show more" jusqu'à ce qu'il n'y en ait plus
        show_more_clicks = 0
        while show_more_clicks < max_show_more_clicks:
            try:
                # On cherche un élément "Show more"
                # Essai avec get_by_text (Playwright 1.28+) puis fallback locator
                btn = page.get_by_text("Show more").first
            except Exception:
                btn = page.locator("text=Show more").first

            try:
                if not btn or btn.count() == 0:
                    print("[scroll_clearance_page] No 'Show more' button found, stopping.")
                    break

                if not btn.is_visible():
                    print("[scroll_clearance_page] 'Show more' button not visible, stopping.")
                    break

                show_more_clicks += 1
                print(f"[scroll_clearance_page] Clicking 'Show more' ({show_more_clicks}/{max_show_more_clicks})")
                btn.click()
                # Laisser du temps pour charger les nouveaux produits
                sleep_time = pause_sec + random.uniform(0.5, 1.5)
                page.wait_for_timeout(int(sleep_time * 1000))

                # Optionnel : un petit scroll pour bien déclencher les loads
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(int(pause_sec * 1000))

            except PlaywrightTimeoutError:
                print("[scroll_clearance_page] Timeout while clicking 'Show more', stopping.")
                break
            except Exception as e:
                print(f"[scroll_clearance_page] Error while clicking 'Show more': {e}")
                break

        # 3) HTML final après tous les clicks
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
