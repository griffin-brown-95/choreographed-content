"""Download daily Wikipedia pageviews, saving one JSON file per article."""

import csv
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx

from ingest.common import (
    RAW_DIR,
    SEEDS_DIR,
    configure_logging,
    get_with_retries,
    load_pipeline_config,
    make_client,
)

API_ROOT = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"
)

logger = logging.getLogger(__name__)


def load_articles() -> list[str]:
    with (SEEDS_DIR / "titles.csv").open(newline="") as file:
        return [row["wikipedia_article"] for row in csv.DictReader(file)]


def pageviews_url(article: str, start: date, end: date) -> str:
    return f"{API_ROOT}/{quote(article, safe='')}/daily/{start:%Y%m%d}/{end:%Y%m%d}"


def find_missing_days(items: list[dict], start: date, end: date) -> list[date]:
    found = {datetime.strptime(item["timestamp"][:8], "%Y%m%d").date() for item in items}
    days = (start + timedelta(days=offset) for offset in range((end - start).days + 1))
    return [day for day in days if day not in found]


def fetch_article(
    client: httpx.Client,
    article: str,
    start: date,
    end: date,
    out_dir: Path,
    backoff_seconds: float = 1.0,
) -> bool:
    """Save one article's pageviews. Returns False if the failure needs attention.

    A 404 means Wikimedia has no data for the article, so it is logged and skipped.
    """
    url = pageviews_url(article, start, end)
    try:
        response = get_with_retries(client, url, backoff_seconds=backoff_seconds)
    except httpx.HTTPError as error:
        logger.error("%s: request failed: %s", article, error)
        return False

    if response.status_code == 404:
        logger.warning("%s: no pageview data (404), skipping", article)
        return True
    if response.status_code != 200:
        logger.error("%s: unexpected status %d", article, response.status_code)
        return False

    payload = response.json()
    (out_dir / f"{article}.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    items = payload.get("items", [])
    missing = find_missing_days(items, start, end)
    if missing:
        logger.warning(
            "%s: %d days saved, %d missing (%s to %s)",
            article,
            len(items),
            len(missing),
            missing[0],
            missing[-1],
        )
    else:
        logger.info("%s: %d days saved, none missing", article, len(items))
    return True


def main() -> int:
    configure_logging()
    window = load_pipeline_config()["window"]
    out_dir = RAW_DIR / "pageviews"
    out_dir.mkdir(parents=True, exist_ok=True)

    with make_client() as client:
        results = [
            fetch_article(client, article, window["start"], window["end"], out_dir)
            for article in load_articles()
        ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
