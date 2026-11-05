from pathlib import Path

import pandas as pd

from ingest.fixtures import FIXTURES_DIR, restore
from ingest.generate_partner_data import generate


def run_generator(raw_dir: Path, truth: dict | None = None) -> pd.DataFrame:
    restore(FIXTURES_DIR, raw_dir)
    return generate(raw_dir, raw_dir / "sku_crosswalk.csv", truth)
