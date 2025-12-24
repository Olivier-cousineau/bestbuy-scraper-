"""Clean Best Buy clearance data and export simplified JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

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


def normalize_url(url: str) -> str:
    """Normalize a BestBuy product URL by stripping query and fragments."""

    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def fetch_og_image(url: str, retries: int = 2, timeout: int = 10) -> Optional[str]:
    """Fetch the og:image URL from a BestBuy product page."""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            tag = soup.find("meta", attrs={"property": "og:image"})
            if tag and tag.get("content"):
                return tag["content"].strip()
        except requests.RequestException:
            if attempt >= retries:
                return None
            time.sleep(1 + attempt)
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
        "price_raw": price_raw,
    }


def dedupe_products(products: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate products based on product ID or URL."""

    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for product in products:
        url = product["url"]
        key = extract_pid(url) or normalize_url(url)
        if key in seen:
            continue
        seen.add(key)
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


def add_images(
    products: List[Dict[str, Any]],
    max_images: int,
    concurrency: int,
    retries: int,
) -> Tuple[int, List[str]]:
    """Fetch og:image URLs with concurrency and update product entries."""

    images_added = 0
    example_images: List[str] = []
    url_cache: Dict[str, Optional[str]] = {}

    tasks: List[Tuple[int, str]] = []
    for index, product in enumerate(products):
        if len(tasks) >= max_images:
            break
        fetch_url = normalize_url(product["url"])
        if fetch_url in url_cache:
            continue
        tasks.append((index, fetch_url))

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_map = {
            executor.submit(fetch_og_image, url, retries): (index, url)
            for index, url in tasks
        }
        for future in as_completed(future_map):
            index, url = future_map[future]
            image_url = future.result()
            url_cache[url] = image_url

            if image_url:
                products[index]["image"] = image_url
                images_added += 1
                if len(example_images) < 2:
                    example_images.append(image_url)

    for product in products:
        fetch_url = normalize_url(product["url"])
        product["image"] = url_cache.get(fetch_url)

    return images_added, example_images


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
    parser.add_argument(
        "--max-images",
        type=int,
        default=300,
        help="Maximum number of products to fetch og:image for.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Number of concurrent requests for fetching og:image URLs.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Number of retries for fetching og:image URLs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input.exists():
        raise FileNotFoundError(f"{args.input} not found")

    raw_products = json.loads(args.input.read_text(encoding="utf-8"))
    cleaned_products = clean_products(raw_products)
    total_items = len(cleaned_products)
    images_added, examples = add_images(
        cleaned_products,
        max_images=args.max_images,
        concurrency=args.concurrency,
        retries=args.retries,
    )

    print(f"Products: {total_items}, Images added: {images_added}")
    if examples:
        print("Example images:")
        for example in examples:
            print(f"- {example}")
    if images_added == 0:
        print("No images were added to the cleaned products. Aborting.")
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cleaned_products, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
