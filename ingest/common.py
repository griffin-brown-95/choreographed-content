"""Shared paths, config, and HTTP helpers for the ingest scripts."""

import logging
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
SEEDS_DIR = ROOT / "dbt" / "fandom_ledger" / "seeds"

# Wikimedia requires a descriptive User-Agent that says who is calling.
USER_AGENT = "FandomLedger/0.1 (https://github.com/griffin-brown-95/choreographed-content)"
RETRY_STATUSES = {429, 500, 502, 503, 504}

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def load_pipeline_config() -> dict:
    return yaml.safe_load((ROOT / "config" / "pipeline.yml").read_text())


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=30,
        follow_redirects=True,
        transport=transport,
    )


def get_with_retries(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    attempts: int = 4,
    backoff_seconds: float = 1.0,
) -> httpx.Response:
    """GET a URL, retrying rate limits, server errors, and connection failures.

    Other statuses, such as 404, are returned for the caller to handle.
    """
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as error:
            if attempt == attempts:
                raise
            logger.warning("Attempt %d for %s failed: %s", attempt, url, error)
        else:
            if response.status_code not in RETRY_STATUSES or attempt == attempts:
                return response
            logger.warning("Attempt %d for %s returned %d", attempt, url, response.status_code)
        time.sleep(backoff_seconds * 2 ** (attempt - 1))
    raise ValueError("attempts must be at least 1")
