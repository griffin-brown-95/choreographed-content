from pathlib import Path

import pandas as pd
import pytest

from tests.helpers import run_generator


@pytest.fixture(scope="session")
def generated(tmp_path_factory) -> tuple[Path, pd.DataFrame]:
    path = tmp_path_factory.mktemp("raw")
    return path, run_generator(path)


@pytest.fixture(scope="session")
def raw_dir(generated) -> Path:
    return generated[0]


@pytest.fixture(scope="session")
def sales(generated) -> pd.DataFrame:
    return generated[1]
