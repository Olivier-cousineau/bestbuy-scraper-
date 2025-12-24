"""Clean Best Buy clearance data and export simplified JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REVIEW_COUNTER_PATTERN = re.compile(r"^\(\d+\)$")
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")
PID_PATTERN = re.compile(r"/(\d+)(?:$|\\?)")


def is_review_counter(title: str) -> bool:
    """Return True when the title is just a review counter like "(24)"."""

    return bool(REVIEW_COUNTER_PATTERN.fullmatch(title.strip()))


def extract_price(price_raw: str) -> Optional[float]:
    """Extract the last numeric price value from a raw price string.

    Removes commas before parsing and returns ``None`` when no numeric portion is
    found or parsing fails.
    """

    cleaned_raw = price_raw.replace(",", "")
    matches = NUMBER_PATTERN.findall(cleaned_raw)
    if not matches:
        return None

    try:
        return float(matches[-1])
    except ValueError:
        return None


def extract_pid(url: str) -> Optional[str]:
    """Extract the product ID (pid) from the end of a BestBuy product URL."""

    match = PID_PATTERN.search(url)
    if not match:
        return None
    return match.group(1)


def build_image_url(pid: str) -> Optional[str]:
    """Build the BestBuy image URL for a product ID."""

    if len(pid) < 5:
        return None
    return (
        "https://multimedia.bbycastatic.ca/multimedia/Products/500x500/"
        f"{pid[:3]}/{pid[:5]}/{pid}.jpg"
    )


def clean_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize and validate a single clearance product entry."""

    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    price_raw = (item.get("price_raw") or "").strip()

    if not title or not url:
        return None
    if is_review_counter(title):
        return None

    price = extract_price(price_raw)
    if price is None:
        return None

    pid = extract_pid(url)
    image = build_image_url(pid) if pid else None

    return {
        "title": title,
        "name": title,
        "url": url,
        "price": price,
        "price_raw": price_raw,
        "image": image,
    }


def clean_products(products: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clean a collection of raw product dictionaries."""

    cleaned: List[Dict[str, Any]] = []
    for product in products:
        cleaned_item = clean_item(product)
        if cleaned_item:
            cleaned.append(cleaned_item)
    return cleaned


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

    print(f"Images added: {images_added} / {total_items}")
    if images_added == 0:
        print("No images were added to the cleaned products. Aborting.")
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cleaned_products, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
