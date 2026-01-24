import os

BESTBUY_SEED_URL = "https://www.bestbuy.ca/en-ca/collection/clearance-products/113065"
BESTBUY_TOKEN = os.getenv("BESTBUY_TOKEN", "ECONOPLUS")
BESTBUY_TOKEN_HEADER = os.getenv("BESTBUY_TOKEN_HEADER", "X-Token")


def build_bestbuy_headers() -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    if BESTBUY_TOKEN:
        headers[BESTBUY_TOKEN_HEADER] = BESTBUY_TOKEN
    return headers
