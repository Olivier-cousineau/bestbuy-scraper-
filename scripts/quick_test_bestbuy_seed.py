"""Quick verification for BestBuy seed URL scraping."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from bestbuy_scraper.config import BESTBUY_SEED_URL
from bestbuy_scraper.scroll_scraper import scrape_bestbuy_clearance


REQUIRED_FIELDS = ("name", "image", "price", "salePrice", "url")


def validate_products(products: list[dict]) -> None:
    if not products:
        raise AssertionError("No products extracted.")

    missing = []
    for index, product in enumerate(products[:10], start=1):
        for field in REQUIRED_FIELDS:
            value = product.get(field)
            if value is None or value == "":
                missing.append((index, field))

    if missing:
        details = ", ".join(f"#{idx}:{field}" for idx, field in missing)
        raise AssertionError(f"Missing required fields: {details}")


def main() -> int:
    print("[test] Running BestBuy seed URL quick test.")
    print(f"[test] Expected seed URL: {BESTBUY_SEED_URL}")
    _, products = scrape_bestbuy_clearance()
    validate_products(products)
    print(f"[test] Extracted products: {len(products)}")
    print("[test] Required fields present for sample products.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
