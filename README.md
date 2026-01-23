# BestBuy Clearance Scraper

This repository contains a Python scraper to collect clearance products from BestBuy Canada and a GitHub Actions workflow to run the scraper on demand or on a schedule.

## Setup

1. Create a virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the scraper locally to save clearance listings into `data/clearance_products.json`:

```bash
PYTHONPATH=src python -m bestbuy_scraper.scraper
```

You can also override the output path or target URL:

```bash
PYTHONPATH=src python -m bestbuy_scraper.scraper --output /tmp/clearance.json --url "https://www.bestbuy.ca/en-ca/collection/clearance-products/113065"
```

## Workflow

The repository includes a GitHub Actions workflow (`.github/workflows/scrape.yml`) that:

- Runs on demand via the `workflow_dispatch` trigger and every Wednesday/Saturday at 04:00 UTC.
- Installs dependencies.
- Executes the scraper to generate `data/clearance_products.json`.
- Uploads the JSON output as a build artifact named `bestbuy-clearance`.

To trigger the workflow manually, use the **Run workflow** button in the GitHub Actions tab after pushing this repository.
