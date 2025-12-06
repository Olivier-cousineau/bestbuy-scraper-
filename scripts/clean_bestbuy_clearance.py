"""Utilities to clean Best Buy clearance products JSON output."""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


REVIEW_COUNTER_PATTERN = re.compile(r"^\(\d+\)$")
NUMBER_PATTERN = re.compile(r"\d[\d,.]*")


def is_review_counter(title: str) -> bool:
    """Return True when the title is just a review counter like "(24)"."""

    return bool(REVIEW_COUNTER_PATTERN.fullmatch(title.strip()))


def extract_price(price_raw: str) -> Optional[float]:
    """Extract the last numeric price value from a raw price string.

    Supports values with commas or periods as thousands/decimal separators.
    Returns None when no numeric component is found.
    """

    matches = NUMBER_PATTERN.findall(price_raw)
    if not matches:
        return None

    last_value = matches[-1].replace(",", "")
    try:
        return float(last_value)
    except ValueError:
        return None


def clean_products(products: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter and normalize clearance product records."""

    cleaned: List[Dict[str, Any]] = []
    for product in products:
        title = str(product.get("title", "")).strip()
        url = str(product.get("url", "")).strip()
        price_raw = str(product.get("price_raw", "")).strip()

        if not title or not url or not price_raw:
            continue
        if is_review_counter(title):
            continue

        price = extract_price(price_raw)
        if price is None:
            continue

        cleaned.append(
            {
                "title": title,
                "url": url,
                "price": price,
                "price_raw": price_raw,
            }
        )

    return cleaned


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clean Best Buy clearance data and output a simplified JSON file with"
            " title, url, price, and price_raw fields."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/clearance_products_full.json"),
        help="Path to the raw clearance JSON file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/bestbuy/clearance.json"),
        help="Destination path for the cleaned JSON file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with args.input.open("r", encoding="utf-8") as f:
        raw_products = json.load(f)

    cleaned_products = clean_products(raw_products)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(cleaned_products, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
