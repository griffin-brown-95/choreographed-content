"""Load every raw file into the DuckDB `raw` schema, exactly as delivered.

Columns stay as text with their original names and mess. Cleaning happens in dbt.
Every run replaces the raw tables in one transaction, so a failed load changes nothing.
"""

import csv
import json
import logging
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
from openpyxl import load_workbook

from ingest.common import RAW_DIR, ROOT, configure_logging

MAISON_HEADER = ["Date Vente", "Ref Article", "Pays", "Qte", "CA Net", "Devise"]
MAISON_TITLE_ROWS = 2

logger = logging.getLogger(__name__)


def default_db_path() -> Path:
    default = ROOT / "data" / "fandom_ledger.duckdb"
    return Path(os.environ.get("FANDOM_LEDGER_DB", default))


def find_files(directory: Path, pattern: str) -> list[Path]:
    paths = sorted(directory.glob(pattern))
    if not paths:
        raise FileNotFoundError(f"No {pattern} files in {directory}")
    return paths


def as_text_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows).astype(str)


def read_toyworks(raw_dir: Path) -> pd.DataFrame:
    rows = []
    for path in find_files(raw_dir / "partner_a", "*.csv"):
        with path.open(newline="") as file:
            rows.extend({**row, "_source_file": path.name} for row in csv.DictReader(file))
    return as_text_frame(rows)


def read_maison_merch(raw_dir: Path) -> pd.DataFrame:
    rows = []
    for path in find_files(raw_dir / "partner_b", "*.xlsx"):
        workbook = load_workbook(path, read_only=True, data_only=True)
        values = workbook.active.iter_rows(min_row=MAISON_TITLE_ROWS + 1, values_only=True)
        header = list(next(values))
        if header != MAISON_HEADER:
            raise ValueError(f"{path.name}: unexpected header {header}")
        rows.extend(
            {**dict(zip(header, row, strict=True)), "_source_file": path.name} for row in values
        )
        workbook.close()
    return as_text_frame(rows)


def read_vault(raw_dir: Path) -> pd.DataFrame:
    """Keep one row per export, with orders as JSON text for dbt to unnest."""
    rows = []
    for path in find_files(raw_dir / "partner_c", "*.json"):
        export = json.loads(path.read_text())
        rows.append(
            {
                "export_id": export["export_id"],
                "generated_at": export["generated_at"],
                "orders": json.dumps(export["orders"]),
                "_source_file": path.name,
            }
        )
    return as_text_frame(rows)


def read_pageviews(raw_dir: Path) -> pd.DataFrame:
    rows = []
    for path in find_files(raw_dir / "pageviews", "*.json"):
        items = json.loads(path.read_text())["items"]
        rows.extend({**item, "_source_file": path.name} for item in items)
    return as_text_frame(rows)


def read_fx_rates(raw_dir: Path) -> pd.DataFrame:
    rows = []
    for path in find_files(raw_dir / "fx", "*_USD.json"):
        payload = json.loads(path.read_text())
        for rate_date, rates in payload["rates"].items():
            for quote_currency, rate in rates.items():
                rows.append(
                    {
                        "base_currency": payload["base"],
                        "quote_currency": quote_currency,
                        "rate_date": rate_date,
                        "rate": rate,
                        "_source_file": path.name,
                    }
                )
    return as_text_frame(rows)


def read_delivery_manifest(raw_dir: Path) -> pd.DataFrame:
    (path,) = find_files(raw_dir, "delivery_manifest.csv")
    with path.open(newline="") as file:
        return as_text_frame([{**row, "_source_file": path.name} for row in csv.DictReader(file)])


READERS: dict[str, Callable[[Path], pd.DataFrame]] = {
    "toyworks_sales": read_toyworks,
    "maison_merch_sales": read_maison_merch,
    "vault_exports": read_vault,
    "wikipedia_pageviews": read_pageviews,
    "frankfurter_fx_rates": read_fx_rates,
    "delivery_manifest": read_delivery_manifest,
}


def load(raw_dir: Path, db_path: Path) -> dict[str, int]:
    """Replace all raw tables. Returns the row count per table."""
    # Read everything first, so a bad file fails before the database is touched.
    frames = {table: reader(raw_dir) for table, reader in READERS.items()}
    loaded_at = datetime.now(UTC).replace(tzinfo=None)

    with duckdb.connect(str(db_path)) as connection:
        connection.begin()
        connection.execute("create schema if not exists raw")
        for table, frame in frames.items():
            connection.register("frame_to_load", frame.assign(_loaded_at=loaded_at))
            connection.execute(f"create or replace table raw.{table} as from frame_to_load")
            connection.unregister("frame_to_load")
        connection.commit()
    return {table: len(frame) for table, frame in frames.items()}


def main() -> int:
    configure_logging()
    try:
        counts = load(RAW_DIR, default_db_path())
    except FileNotFoundError as error:
        logger.error("%s. Run make fetch and make generate first.", error)
        return 1
    except duckdb.IOException as error:
        logger.error(
            "Could not open the database: %s\n"
            "If it is attached in the VS Code DuckDB extension or open in the Dash app, "
            "detach or stop it and run this again.",
            error,
        )
        return 1
    for table, count in counts.items():
        logger.info("raw.%s: %d rows", table, count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
