"""Clean Best Buy clearance data and export simplified JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REVIEW_COUNTER_PATTERN = re.compile(r"^\(\d+\)$")
PID_PATTERN = re.compile(r"/(\d+)(?:[?#].*)?$")
NUMBER_PATTERN = re.compile(r"\d[\d,.]*")


def is_review_counter(title: str) -> bool:
    """Return True when the title is just a review counter like "(24)"."""

    stripped = title.strip()
    return bool(REVIEW_COUNTER_PATTERN.fullmatch(stripped)) or stripped.startswith("(")


def extract_pid(url: str) -> Optional[str]:
    """Extract the product ID (pid) from the end of a BestBuy product URL."""

    match = PID_PATTERN.search(url)
    if not match:
        return None
    return match.group(1)


def extract_price(price_raw: str) -> Optional[float]:
    """Extract the last numeric price value from a raw price string."""

    matches = NUMBER_PATTERN.findall(price_raw)
    if not matches:
        return None

    last_value = matches[-1].replace(",", "")
    try:
        return float(last_value)
    except ValueError:
        return None


def clean_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize and validate a single clearance product entry."""

    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    price_raw = (item.get("price_raw") or "").strip()
    image = item.get("image")

    if not title or not url:
        return None
    if is_review_counter(title):
        return None
    if not image:
        return None
    price = extract_price(price_raw)
    if price is None:
        return None

    return {
        "title": title,
        "url": url,
        "price": price,
        "price_raw": price_raw,
        "image": image,
    }


def dedupe_products(products: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate products based on BestBuy product ID."""

    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for product in products:
        url = product["url"]
        product_id = extract_pid(url)
        if product_id:
            if product_id in seen:
                continue
            seen.add(product_id)
        deduped.append(product)
    return deduped


def clean_products(products: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clean a collection of raw product dictionaries."""

    cleaned: List[Dict[str, Any]] = []
    for product in products:
        cleaned_item = clean_item(product)
        if cleaned_item:
            cleaned.append(cleaned_item)
    return dedupe_products(cleaned)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Clean BestBuy clearance data into a normalized JSON file."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=root / "data" / "clearance_products_full.json",
        help="Path to the raw clearance JSON file produced by the scraper.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "outputs" / "bestbuy" / "clearance.json",
        help="Destination path for the cleaned clearance JSON file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input.exists():
        raise FileNotFoundError(f"{args.input} not found")

    raw_products = json.loads(args.input.read_text(encoding="utf-8"))
    cleaned_products = clean_products(raw_products)
    total_items = len(cleaned_products)
    images_added = sum(1 for product in cleaned_products if product.get("image"))

    print(f"Products: {total_items}, Images added: {images_added}")
    if images_added == 0:
        print("No images were found in the cleaned products. Aborting.")
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cleaned_products, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
