from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "dbt" / "fandom_ledger" / "seeds"


def read_csv(path: Path) -> pd.DataFrame:
    # keep_default_na=False stops codes such as "NA" from being read as null.
    return pd.read_csv(path, dtype=str, keep_default_na=False)


@pytest.fixture(scope="module")
def window() -> dict:
    config = yaml.safe_load((ROOT / "config" / "pipeline.yml").read_text())
    return config["window"]


@pytest.fixture(scope="module")
def titles() -> pd.DataFrame:
    return read_csv(SEEDS / "titles.csv")


@pytest.fixture(scope="module")
def launches() -> pd.DataFrame:
    return read_csv(SEEDS / "title_launches.csv")


@pytest.fixture(scope="module")
def catalog() -> pd.DataFrame:
    return read_csv(ROOT / "config" / "sku_catalog.csv")


def test_launch_windows_fit_inside_date_window(launches, window):
    launch_dates = pd.to_datetime(launches["launch_date"])
    assert (launch_dates - pd.Timedelta(days=30) >= pd.Timestamp(window["start"])).all()
    assert (launch_dates + pd.Timedelta(days=90) <= pd.Timestamp(window["end"])).all()


def test_no_sales_start_after_first_launch(titles, launches):
    first_launch = launches.groupby("title_id")["launch_date"].min()
    first_sale = titles.set_index("title_id")["first_sale_date"]
    assert (first_sale <= first_launch.reindex(first_sale.index)).all()


def test_every_title_has_a_launch(titles, launches):
    assert set(titles["title_id"]) == set(launches["title_id"])


def test_catalog_skus_are_unique_per_partner(catalog):
    assert not catalog.duplicated(["partner_id", "partner_sku"]).any()


def test_catalog_titles_exist(catalog, titles):
    assert set(catalog["title_id"]) <= set(titles["title_id"])


def test_crosswalk_is_the_mapped_part_of_the_catalog(catalog):
    columns = ["partner_id", "partner_sku", "title_id", "product_category"]
    expected = catalog.loc[catalog["in_crosswalk"] == "true", columns]
    crosswalk = read_csv(SEEDS / "sku_crosswalk.csv")
    pd.testing.assert_frame_equal(
        crosswalk.sort_values(columns).reset_index(drop=True),
        expected.sort_values(columns).reset_index(drop=True),
    )


def test_about_three_percent_of_skus_are_unmapped(catalog):
    unmapped_share = (catalog["in_crosswalk"] == "false").mean()
    assert 0.02 <= unmapped_share <= 0.04


def test_every_partner_has_an_unmapped_sku(catalog):
    unmapped = catalog.loc[catalog["in_crosswalk"] == "false", "partner_id"]
    assert set(unmapped) == set(catalog["partner_id"])


def test_partners_use_inconsistent_uk_codes():
    regions = read_csv(SEEDS / "regions.csv")
    uk = regions[regions["country_code"] == "GB"]
    assert set(uk["raw_country_code"]) == {"UK", "GB"}
