"""Clean Best Buy clearance data and export simplified JSON."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "clearance_products_full.json"
OUTPUT_DIR = ROOT / "outputs" / "bestbuy"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT = OUTPUT_DIR / "clearance.json"

REVIEW_COUNTER_PATTERN = re.compile(r"^\(\d+\)$")
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


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

    return {
        "title": title,
        "url": url,
        "price": price,
        "price_raw": price_raw,
    }


def clean_products(products: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clean a collection of raw product dictionaries."""

    cleaned: List[Dict[str, Any]] = []
    for product in products:
        cleaned_item = clean_item(product)
        if cleaned_item:
            cleaned.append(cleaned_item)
    return cleaned


def main() -> None:
    if not INPUT.exists():
        raise FileNotFoundError(f"{INPUT} not found")

    raw_products = json.loads(INPUT.read_text(encoding="utf-8"))
    cleaned_products = clean_products(raw_products)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(cleaned_products, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
