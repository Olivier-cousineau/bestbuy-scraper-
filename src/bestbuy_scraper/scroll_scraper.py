# src/bestbuy_scraper/scroll_scraper.py

import json
import random
import time
from pathlib import Path
from typing import Dict, List, Tuple

from playwright.sync_api import sync_playwright


CLEARANCE_URL = "https://www.bestbuy.ca/en-ca/collection/clearance-products/113065"


def click_show_more(page, pause_sec: float = 1.5, max_clicks: int = 40):
    """
    Clique sur le bouton 'Show more' BestBuy autant de fois que possible.

    - Le bouton est identifié par data-automation="load-more"
    - On limite le nombre de clics à max_clicks par sécurité.
    """
    clicks = 0
    while clicks < max_clicks:
        locator = page.locator('button[data-automation="load-more"]')
        try:
            if not locator or locator.count() == 0:
                print("[click_show_more] Aucun bouton 'Show more' trouvé, arrêt.")
                break
            if not locator.first.is_visible():
                print("[click_show_more] Bouton 'Show more' non visible, arrêt.")
                break

            print(f"[click_show_more] Bouton détecté — clic {clicks+1}/{max_clicks}…")
            try:
                locator.first.click(timeout=8000)
            except Exception as e:
                print(f"[click_show_more] Échec du clic normal ({e}), tentative via JS…")
                page.evaluate(
                    """() => {
                        const btn = document.querySelector('button[data-automation="load-more"]');
                        if (btn) btn.click();
                    }"""
                )

            clicks += 1
            sleep_time = pause_sec + random.uniform(0.5, 1.5)
            page.wait_for_timeout(int(sleep_time * 1000))

        except Exception as e:
            print(f"[click_show_more] Erreur lors de la gestion du bouton 'Show more': {e}")
            break

    print(f"[click_show_more] Terminé, total de clics: {clicks}")


def extract_products_from_page(page) -> List[Dict]:
    """
    Extract products directly from the live DOM after scrolling.
    Returns a list with title, url, price_raw, and image fields.
    """
    products = page.evaluate(
        """() => {
            const results = [];
            const seen = new Set();

            const CARD_SELECTORS = [
                "div.style-module_sliderTarget__z6XJY",
                "a[href*='/en-ca/product/']",
                "a[href*='/product/']",
                "[data-automation='product-card']",
                "[class*='productCard']",
                "[class*='product-card']"
            ];

            const extractPriceToken = (container) => {
                if (!container) return null;
                const text = container.innerText || "";
                const lines = text.split(/\\n+/).map((line) => line.trim()).filter(Boolean);
                for (const line of lines) {
                    if (line.includes("$")) {
                        return line;
                    }
                }
                return null;
            };

            const getCardForAnchor = (anchor) => {
                if (!anchor) return null;
                return (
                    anchor.closest(
                        "[data-automation='product-card'], [class*='product-card'], [class*='productCard'], [class*='product']"
                    ) || anchor.closest("div")
                );
            };

            let chosenSelector = null;
            let cardNodes = [];
            for (const selector of CARD_SELECTORS) {
                const nodes = Array.from(document.querySelectorAll(selector));
                if (nodes.length > 0) {
                    chosenSelector = selector;
                    cardNodes = nodes;
                    break;
                }
            }

            let anchors = [];
            if (chosenSelector && chosenSelector.startsWith("a[")) {
                anchors = cardNodes;
            } else if (cardNodes.length > 0) {
                anchors = cardNodes
                    .map((node) =>
                        node.querySelector("a[href*='/en-ca/product/'], a[href*='/product/']")
                    )
                    .filter(Boolean);
            } else {
                anchors = Array.from(
                    document.querySelectorAll(
                        "a[href*='/en-ca/product/'], a[href*='/product/']"
                    )
                );
            }

            for (const anchor of anchors) {
                const href = anchor.getAttribute("href");
                if (!href) continue;
                const url = href.startsWith("/")
                    ? `https://www.bestbuy.ca${href}`
                    : href;
                if (seen.has(url)) continue;

                const card = getCardForAnchor(anchor);
                const titleEl = card
                    ? card.querySelector("span.truncate, span[class*='truncate']")
                    : null;
                const rawTitle = titleEl
                    ? titleEl.innerText.trim()
                    : (anchor.innerText || "").trim();
                const title = rawTitle.replace(/\\s+/g, " ").trim();
                if (!title) continue;
                if (/^\\(\\d+\\)$/.test(title) || title.startsWith("(")) {
                    continue;
                }

                const img = card ? card.querySelector("img") : null;
                const image = img
                    ? img.getAttribute("src") ||
                      img.getAttribute("data-src") ||
                      img.currentSrc
                    : null;

                const priceRaw = extractPriceToken(card);

                results.push({
                    title,
                    url,
                    price_raw: priceRaw,
                    image,
                });
                seen.add(url);
            }

            return results;
        }"""
    )
    total_products = len(products)
    images_found = sum(1 for product in products if product.get("image"))
    print(f"Extracted products: {total_products}")
    print(f"Images found: {images_found}")
    for idx, product in enumerate(
        [product for product in products if product.get("image")][:2]
        or products[:2],
        start=1,
    ):
        print(f"Example {idx}: {product.get('title')} -> {product.get('image')}")
    return products


def wait_after_show_more(page) -> None:
    print("[wait_after_show_more] Waiting after show more clicks.")
    page.wait_for_timeout(2000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception as e:
        print(f"[wait_after_show_more] networkidle wait failed ({e}), using domcontentloaded.")
        page.wait_for_load_state("domcontentloaded", timeout=30000)


def scroll_clearance_page(max_scrolls: int = 5, pause_sec: float = 1.5, max_show_more_clicks: int = 40) -> str:
    """
    Ouvre la page clearance BestBuy et :
      1) fait quelques scrolls initiaux
      2) clique plusieurs fois sur le bouton "Show more" (data-automation="load-more")
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

        # 1) Scroll léger pour initialiser la page et déclencher les premiers chargements
        last_height = page.evaluate("document.body.scrollHeight")
        for i in range(max_scrolls):
            print(f"[scroll_clearance_page] Initial scroll {i+1}/{max_scrolls}")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            sleep_time = pause_sec + random.uniform(0.2, 0.8)
            page.wait_for_timeout(int(sleep_time * 1000))
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        # 2) Cliquer sur le bouton "Show more" autant que possible
        click_show_more(page, pause_sec=pause_sec, max_clicks=max_show_more_clicks)

        wait_after_show_more(page)

        # 3) HTML final après tous les clicks
        html = page.content()
        browser.close()
        return html


def scrape_bestbuy_clearance() -> Tuple[str, List[Dict]]:
    """
    Pipeline complet :
      1) Scroll la page BestBuy clearance
      2) Extract tous les produits du HTML complet

    Retourne un tuple ``(html, products)`` pour pouvoir persister le HTML brut
    ainsi que la liste d'objets JSON.
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
        print(f"[scrape_bestbuy_clearance] Opening {CLEARANCE_URL}")
        page.goto(CLEARANCE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        last_height = page.evaluate("document.body.scrollHeight")
        for i in range(5):
            print(f"[scrape_bestbuy_clearance] Initial scroll {i+1}/5")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            sleep_time = 1.5 + random.uniform(0.2, 0.8)
            page.wait_for_timeout(int(sleep_time * 1000))
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        click_show_more(page, pause_sec=1.5, max_clicks=40)

        wait_after_show_more(page)

        products = extract_products_from_page(page)
        if not products:
            debug_dir = Path("outputs/debug")
            debug_dir.mkdir(parents=True, exist_ok=True)
            html_path = debug_dir / "bb_after_showmore.html"
            screenshot_path = debug_dir / "bb_after_showmore.png"
            html_path.write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(screenshot_path), full_page=True)

            anchor_count = page.evaluate(
                """() => document.querySelectorAll("a[href*='/product/']").length"""
            )
            image_count = page.evaluate("""() => document.querySelectorAll("img").length""")
            sample_hrefs = page.evaluate(
                """() => Array.from(
                    document.querySelectorAll("a[href*='/product/']")
                ).slice(0, 5).map((anchor) => anchor.getAttribute("href"))"""
            )
            print(f"[debug] Anchor count: {anchor_count}")
            print(f"[debug] Image count: {image_count}")
            print(f"[debug] Sample hrefs: {sample_hrefs}")

            browser.close()
            raise RuntimeError("No products extracted from BestBuy clearance page.")
        html = page.content()
        browser.close()

    return html, products


def main():
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description="Scrape BestBuy.ca clearance products via Playwright scroll."
    )
    root = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--output",
        "-o",
        default=root / "data" / "clearance_products_full.json",
        help="Output JSON file path for the raw products list.",
    )
    parser.add_argument(
        "--html",
        default=root / "data" / "clearance_page.html",
        help="Output path for the raw HTML captured after scrolling.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    html_path = Path(args.html)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    html, products = scrape_bestbuy_clearance()

    html_path.write_text(html, encoding="utf-8")
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    print(f"Saved HTML snapshot to {html_path}")
    print(f"Saved {len(products)} clearance products to {output_path}")


if __name__ == "__main__":
    main()
