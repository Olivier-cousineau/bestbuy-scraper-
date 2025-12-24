# src/bestbuy_scraper/scroll_scraper.py

import json
import random
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple

from playwright.sync_api import sync_playwright


CLEARANCE_URL = "https://www.bestbuy.ca/en-ca/collection/clearance-products/113065"
PRODUCT_ID_PATTERN = re.compile(r"/(\d+)(?:[?#].*)?$")


def click_show_more(
    page,
    pause_sec: float = 1.5,
    max_clicks: int = 200,
    stable_iterations: int = 3,
    wait_timeout_sec: float = 15.0,
    poll_interval_sec: float = 0.5,
):
    """
    Clique sur le bouton 'Show more' BestBuy autant de fois que possible.

    - Le bouton est identifié par data-automation="load-more"
    - On limite le nombre de clics à max_clicks par sécurité.
    """
    clicks = 0
    stable_count = 0
    selectors = [
        'button:has-text("Show more")',
        'button:has-text("Voir plus")',
        'button:has-text("Load more")',
        'button:has-text("Charger plus")',
        '[aria-label*="Show more"]',
        '[aria-label*="Voir plus"]',
        '[data-automation*="showMore"]',
        '[data-automation*="loadMore"]',
    ]
    button_selector = ", ".join(selectors)
    while clicks < max_clicks:
        anchors_before = page.evaluate(
            """() => document.querySelectorAll('a[href^="/en-ca/product/"]').length"""
        )
        locator = page.locator(button_selector)
        try:
            if not locator or locator.count() == 0:
                print("[click_show_more] Aucun bouton 'Show more' trouvé, arrêt.")
                break
            button_handle = None
            for idx in range(locator.count()):
                candidate = locator.nth(idx)
                if not candidate.is_visible():
                    continue
                is_disabled = candidate.evaluate(
                    "el => el.disabled || el.getAttribute('aria-disabled') === 'true'"
                )
                if is_disabled:
                    continue
                button_handle = candidate
                break

            if not button_handle:
                print("[click_show_more] Bouton 'Show more' absent ou désactivé, arrêt.")
                break

            print(f"[click_show_more] Bouton détecté — clic {clicks+1}/{max_clicks}…")
            try:
                button_handle.scroll_into_view_if_needed(timeout=8000)
                button_handle.click(timeout=8000)
            except Exception as e:
                print(f"[click_show_more] Échec du clic normal ({e}), tentative via JS…")
                page.evaluate(
                    """(labels, dataKeys) => {
                        const matchesLabel = (value) =>
                            labels.some((label) => value.includes(label));
                        const matchesData = (value) =>
                            dataKeys.some((key) => value.includes(key));
                        const candidates = Array.from(
                            document.querySelectorAll("button, [aria-label], [data-automation]")
                        );
                        const btn = candidates.find((el) => {
                            const text = (el.textContent || "").trim();
                            const aria = (el.getAttribute("aria-label") || "").trim();
                            const data = (el.getAttribute("data-automation") || "").trim();
                            return (
                                matchesLabel(text) ||
                                matchesLabel(aria) ||
                                matchesData(data)
                            );
                        });
                        if (btn) btn.click();
                    }""",
                    ["Show more", "Voir plus", "Load more", "Charger plus"],
                    ["showMore", "loadMore"],
                )

            clicks += 1
            wait_deadline = time.time() + wait_timeout_sec
            anchors_after = anchors_before
            while time.time() < wait_deadline:
                anchors_after = page.evaluate(
                    """() => document.querySelectorAll('a[href^="/en-ca/product/"]').length"""
                )
                if anchors_after > anchors_before:
                    break
                page.wait_for_timeout(int(poll_interval_sec * 1000))

            print(
                "[click_show_more] Iteration "
                f"{clicks}/{max_clicks} "
                f"clickIndex={clicks} countBefore={anchors_before} countAfter={anchors_after}"
            )
            if anchors_after > anchors_before:
                stable_count = 0
            else:
                stable_count += 1
                if stable_count >= stable_iterations:
                    print(
                        "[click_show_more] Stabilisation détectée "
                        f"({stable_count} itérations sans hausse), arrêt."
                    )
                    break

            sleep_time = pause_sec + random.uniform(0.5, 1.5)
            page.wait_for_timeout(int(sleep_time * 1000))

        except Exception as e:
            print(f"[click_show_more] Erreur lors de la gestion du bouton 'Show more': {e}")
            break

    anchors_final = page.evaluate(
        """() => document.querySelectorAll('a[href^="/en-ca/product/"]').length"""
    )
    print(
        "[click_show_more] Terminé "
        f"totalClicks={clicks} anchorsFinal={anchors_final}"
    )


def normalize_display_price(display_price: str) -> str:
    cleaned = re.sub(r"\s+", "", display_price or "").strip()
    if not cleaned:
        return ""
    match = re.search(r"\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?", cleaned)
    return match.group(0) if match else cleaned


def extract_display_price(container) -> str:
    if not container:
        return ""
    elem = container.query_selector('[aria-label*="$"]')
    if elem:
        display_price = (elem.get_attribute("aria-label") or elem.inner_text() or "").strip()
        if display_price:
            return display_price
    elem = container.query_selector(
        'span[class*="price"], div[class*="price"], [data-automation*="price"]'
    )
    if elem:
        display_price = (elem.inner_text() or "").strip()
        if display_price:
            return display_price
    text = container.inner_text() or ""
    match = re.search(r"\$\s*\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})?", text)
    return match.group(0) if match else ""


def extract_products_from_page(page) -> List[Dict]:
    """
    Extract products directly from the live DOM after scrolling.
    Returns a list with title, url, price_raw, salePrice, and image fields.
    """
    anchors = page.query_selector_all('a[href^="/en-ca/product/"]')
    anchors_found = len(anchors)
    print(f"Anchors found: {anchors_found}")

    products = []
    seen_product_ids = set()

    for anchor in anchors:
        href = anchor.get_attribute("href")
        if not href:
            continue
        href_base = href.split("?", 1)[0].split("#", 1)[0]
        if not href_base:
            continue

        url_abs = f"https://www.bestbuy.ca{href_base}"
        container_handle = anchor.evaluate_handle(
            """(a) => {
                const preferred = a.closest("[class*='product'], [class*='Product'], [data-automation]");
                if (preferred) return preferred;
                let node = a.closest("div") || a.parentElement;
                let depth = 0;
                while (node && depth < 6) {
                    if (node.matches &&
                        node.matches("[class*='product'], [class*='Product'], [data-automation]")) {
                        return node;
                    }
                    node = node.parentElement;
                    depth += 1;
                }
                return a.closest("div") || a.parentElement || a;
            }"""
        )
        container = container_handle.as_element()

        title = (anchor.inner_text() or "").strip()
        if not title:
            title = (anchor.get_attribute("aria-label") or "").strip()
        if not title:
            continue
        if re.match(r"^\(\d+\)$", title):
            continue

        image = None
        price_raw = None
        sale_price = None
        if container:
            img = container.query_selector("img")
            if img:
                image = (
                    img.get_attribute("src")
                    or img.get_attribute("data-src")
                    or img.evaluate("img => img.currentSrc")
                )
            display_price = extract_display_price(container)
            normalized_price = normalize_display_price(display_price)
            if normalized_price:
                price_raw = normalized_price
                sale_price = float(re.sub(r"[^0-9.]", "", normalized_price))

        product_id_match = PRODUCT_ID_PATTERN.search(url_abs)
        product_id = product_id_match.group(1) if product_id_match else None
        if product_id:
            if product_id in seen_product_ids:
                continue
            seen_product_ids.add(product_id)

        products.append(
            {
                "title": title,
                "url": url_abs,
                "price_raw": price_raw,
                "salePrice": sale_price,
                "image": image,
            }
        )

    total_products = len(products)
    images_found = sum(1 for product in products if product.get("image"))
    prices_found = sum(1 for product in products if product.get("price_raw"))
    print(f"Extracted products: {total_products}")
    print(f"Images found: {images_found}")
    print(f"Prices found: {prices_found} / {total_products}")
    print(f"Final anchorsFound: {anchors_found}")
    print(f"Final uniqueProducts: {total_products}")
    examples = [product for product in products if product.get("price_raw")][:3]
    for idx, product in enumerate(examples, start=1):
        print(
            f"Example {idx}: {product.get('title')} -> {product.get('price_raw')} -> {product.get('url')}"
        )
    return products


def wait_after_show_more(page) -> None:
    print("[wait_after_show_more] Waiting after show more clicks.")
    page.wait_for_timeout(2000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception as e:
        print(f"[wait_after_show_more] networkidle wait failed ({e}), using domcontentloaded.")
        page.wait_for_load_state("domcontentloaded", timeout=30000)


def scroll_clearance_page(
    max_scrolls: int = 5,
    pause_sec: float = 1.5,
    max_show_more_clicks: int = 200,
) -> str:
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

        click_show_more(page, pause_sec=1.5, max_clicks=200)

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
