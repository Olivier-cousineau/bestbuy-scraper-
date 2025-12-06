import argparse
import json
import pathlib
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional

import requests
from bs4 import BeautifulSoup

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


def fetch_page(url: str, *, timeout: int = 20) -> str:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


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
