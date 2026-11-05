"""Download daily FX rates to USD from Frankfurter, saving one JSON file per currency.

Weekends and holidays have no published rate. Those gaps stay in the raw files,
and dbt forward-fills them.
"""

import json
import logging
import sys
from datetime import date
from pathlib import Path

import httpx

from ingest.common import (
    RAW_DIR,
    configure_logging,
    get_with_retries,
    load_pipeline_config,
    make_client,
)

API_ROOT = "https://api.frankfurter.dev/v1"

logger = logging.getLogger(__name__)


def fetch_currency(
    client: httpx.Client,
    currency: str,
    fetch_start: date,
    window_start: date,
    window_end: date,
    out_dir: Path,
    backoff_seconds: float = 1.0,
) -> None:
    """Save one currency's rates, or raise if they can't cover the date window."""
    url = f"{API_ROOT}/{fetch_start}..{window_end}"
    params = {"base": currency, "symbols": "USD"}
    response = get_with_retries(client, url, params=params, backoff_seconds=backoff_seconds)
    response.raise_for_status()

    payload = response.json()
    rate_dates = sorted(payload.get("rates", {}))
    if not rate_dates or rate_dates[0] > window_start.isoformat():
        raise ValueError(f"{currency}: no rate on or before {window_start} to forward-fill from")

    path = out_dir / f"{currency}_USD.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    logger.info(
        "%s: %d rates saved (%s to %s)", currency, len(rate_dates), rate_dates[0], rate_dates[-1]
    )


def main() -> int:
    configure_logging()
    config = load_pipeline_config()
    out_dir = RAW_DIR / "fx"
    out_dir.mkdir(parents=True, exist_ok=True)

    with make_client() as client:
        for currency in config["fx"]["currencies"]:
            fetch_currency(
                client,
                currency,
                config["fx"]["fetch_start"],
                config["window"]["start"],
                config["window"]["end"],
                out_dir,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
