"""Snapshot real pageviews and FX rates as compact CSVs, and restore them for offline runs.

    python -m ingest.fixtures snapshot   # data/raw -> data/fixtures
    python -m ingest.fixtures restore    # data/fixtures -> data/raw, in the API's file format
"""

import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from ingest.common import RAW_DIR, ROOT, configure_logging

FIXTURES_DIR = ROOT / "data" / "fixtures"

logger = logging.getLogger(__name__)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def snapshot(raw_dir: Path, fixtures_dir: Path) -> None:
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    with (fixtures_dir / "pageviews.csv").open("w", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(["article", "date", "views"])
        for path in sorted((raw_dir / "pageviews").glob("*.json")):
            for item in json.loads(path.read_text())["items"]:
                writer.writerow([path.stem, item["timestamp"][:8], item["views"]])

    with (fixtures_dir / "fx.csv").open("w", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(["currency", "date", "usd_rate"])
        for path in sorted((raw_dir / "fx").glob("*_USD.json")):
            payload = json.loads(path.read_text())
            for rate_date, rates in sorted(payload["rates"].items()):
                writer.writerow([payload["base"], rate_date, rates["USD"]])


def restore(fixtures_dir: Path, raw_dir: Path) -> None:
    pageviews_dir = raw_dir / "pageviews"
    fx_dir = raw_dir / "fx"
    pageviews_dir.mkdir(parents=True, exist_ok=True)
    fx_dir.mkdir(parents=True, exist_ok=True)

    articles = defaultdict(list)
    with (fixtures_dir / "pageviews.csv").open(newline="") as file:
        for row in csv.DictReader(file):
            articles[row["article"]].append(
                {
                    "access": "all-access",
                    "agent": "user",
                    "article": row["article"],
                    "granularity": "daily",
                    "project": "en.wikipedia",
                    "timestamp": f"{row['date']}00",
                    "views": int(row["views"]),
                }
            )
    for article, items in articles.items():
        write_json(pageviews_dir / f"{article}.json", {"items": items})

    currencies = defaultdict(dict)
    with (fixtures_dir / "fx.csv").open(newline="") as file:
        for row in csv.DictReader(file):
            currencies[row["currency"]][row["date"]] = {"USD": float(row["usd_rate"])}
    for currency, rates in currencies.items():
        payload = {
            "amount": 1.0,
            "base": currency,
            "end_date": max(rates),
            "rates": rates,
            "start_date": min(rates),
        }
        write_json(fx_dir / f"{currency}_USD.json", payload)


def main() -> int:
    configure_logging()
    command = sys.argv[1] if len(sys.argv) == 2 else ""
    if command == "snapshot":
        snapshot(RAW_DIR, FIXTURES_DIR)
    elif command == "restore":
        restore(FIXTURES_DIR, RAW_DIR)
    else:
        logger.error("Usage: python -m ingest.fixtures [snapshot|restore]")
        return 2
    logger.info("%s finished", command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
