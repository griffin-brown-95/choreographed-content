"""Check that the built marts recover what the generator planted.

These tests need a built database, so they run with `make recover`, not `make test`.
Thresholds come from config/ground_truth.yml, the same file that drives the generator.
"""

from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml

from ingest.common import RAW_DIR, ROOT, load_pipeline_config
from ingest.generate_partner_data import (
    load_catalog,
    load_ground_truth,
    load_titles,
    make_random_streams,
    simulate_sales,
)
from ingest.load_raw import default_db_path

pytestmark = pytest.mark.recovery

MARTS_DIR = ROOT / "dbt" / "fandom_ledger" / "models" / "marts"
TESTED_FINDINGS = {
    "maison_best_in_eu",
    "vault_strongest_on_anime_animation_ip",
    "bridgerton_high_buzz_weak_conversion",
    "partner_lags",
}


@pytest.fixture(scope="module")
def truth() -> dict:
    return load_ground_truth()


@pytest.fixture(scope="module")
def findings(truth) -> dict:
    return {finding["id"]: finding for finding in truth["expected_findings"]}


@pytest.fixture(scope="module")
def connection():
    path: Path = default_db_path()
    if not path.exists():
        pytest.fail(f"No database at {path}. Run make build first.")
    with duckdb.connect(str(path), read_only=True) as read_only_connection:
        yield read_only_connection


@pytest.fixture(scope="module")
def conversion(connection) -> pd.DataFrame:
    return connection.execute("select * from marts.mart_partner_conversion").df()


@pytest.fixture(scope="module")
def data_health(connection) -> pd.DataFrame:
    return connection.execute("select * from marts.mart_data_health").df()


@pytest.fixture(scope="module")
def true_sales(truth) -> pd.DataFrame:
    sales_stream = make_random_streams(truth["seed"])[0]
    window_end = pd.Timestamp(load_pipeline_config()["window"]["end"])
    return simulate_sales(
        truth, load_titles(), load_catalog(), RAW_DIR / "pageviews", window_end, sales_stream
    )


def conversion_by_title(conversion: pd.DataFrame, region: str) -> pd.DataFrame:
    rows = conversion[conversion.region == region]
    return rows.pivot(index="title_id", columns="partner_id", values="revenue_per_1k_pageviews")


def test_every_expected_finding_has_a_test(findings):
    assert set(findings) == TESTED_FINDINGS


def test_maison_merch_beats_vault_in_the_eu_on_every_title(conversion, findings):
    finding = findings["maison_best_in_eu"]
    by_title = conversion_by_title(conversion, finding["region"])
    shared = by_title[[finding["partner"], finding["compared_to"]]].dropna()
    ratios = shared[finding["partner"]] / shared[finding["compared_to"]]

    assert len(shared) > 0
    assert ratios.min() >= finding["min_ratio"], ratios.to_dict()


def test_vault_has_the_strongest_response_on_anime_animation_ip(conversion, findings):
    finding = findings["vault_strongest_on_anime_animation_ip"]
    by_title = conversion_by_title(conversion, finding["region"])
    shared = by_title[[finding["partner"], finding["compared_to"]]].dropna()
    ratios = shared[finding["partner"]] / shared[finding["compared_to"]]
    segments = conversion.drop_duplicates("title_id").set_index("title_id").fan_segment
    is_target = segments.reindex(ratios.index) == finding["fan_segment"]

    lift = ratios[is_target].mean() / ratios[~is_target].mean()

    assert lift >= finding["min_lift"], ratios.to_dict()


def test_planted_title_has_high_buzz_but_the_weakest_conversion(conversion, findings):
    finding = findings["bridgerton_high_buzz_weak_conversion"]
    by_title = conversion.groupby("title_id").agg(
        revenue_usd=("revenue_usd", "sum"), pageviews=("pageviews", "max")
    )
    revenue_per_view = by_title.revenue_usd.astype(float) / by_title.pageviews
    buzz_rank = by_title.pageviews.rank(ascending=False)[finding["title"]]

    assert revenue_per_view.idxmin() == finding["title"], revenue_per_view.to_dict()
    assert buzz_rank <= finding["max_buzz_rank"]


def test_median_best_lag_matches_each_partners_planted_lag(connection, findings, truth):
    best_lags = connection.execute(
        "select partner_id, lag_days from marts.mart_buzz_sales_lag where is_best_lag"
    ).df()
    medians = best_lags.groupby("partner_id").lag_days.median()
    tolerance = findings["partner_lags"]["tolerance_days"]

    assert set(medians.index) == set(truth["partners"])
    for partner_id, partner in truth["partners"].items():
        assert abs(medians[partner_id] - partner["lag_days"]) <= tolerance, medians.to_dict()


def test_mapped_units_match_true_sales_on_every_date_and_sku(connection, true_sales):
    mapped = connection.execute(
        """
        select partner_id, sale_date, partner_sku, sum(units) as units
        from intermediate.int_partner_sales_mapped
        group by partner_id, sale_date, partner_sku
        """
    ).df()
    keys = ["partner_id", "sale_date", "partner_sku"]
    mapped["sale_date"] = pd.to_datetime(mapped.sale_date)
    actual = mapped.set_index(keys).units.astype(int).sort_index()
    expected = true_sales.groupby(keys).units.sum().astype(int).sort_index()

    pd.testing.assert_series_equal(actual, expected, check_names=False, check_index_type=False)


def test_vault_units_land_on_the_true_utc_date_and_country(connection, true_sales):
    vault = connection.execute(
        """
        select sale_date, partner_sku, country_code, sum(units) as units
        from staging.stg_vault__order_lines
        group by sale_date, partner_sku, country_code
        """
    ).df()
    keys = ["sale_date", "partner_sku", "country_code"]
    vault["sale_date"] = pd.to_datetime(vault.sale_date)
    actual = vault.set_index(keys).units.astype(int).sort_index()
    rows = true_sales[true_sales.partner_id == "vault"]
    expected = rows.groupby(keys).units.sum().astype(int).sort_index()

    pd.testing.assert_series_equal(actual, expected, check_names=False, check_index_type=False)


def test_restatement_factors_are_recovered(data_health, truth):
    rows = data_health[data_health.check_name == "restatement"].set_index("subject")
    planted = truth["mess"]["maison_merch"]["restatements"]

    assert set(rows.index) == {item["month"] for item in planted}
    for item in planted:
        row = rows.loc[item["month"]]
        factor = float(row.original_amount_usd) / float(row.amount_usd)
        assert factor == pytest.approx(item["v1_revenue_factor"], abs=0.001)


def test_only_the_planted_late_file_is_reported(data_health, truth):
    late_month = truth["mess"]["toyworks"]["late_month"].replace("-", "_")
    rows = data_health[data_health.check_name == "late_file"]

    assert rows.subject.tolist() == [f"toyworks_sales_{late_month}.csv"]
    assert rows.days_late.iloc[0] > 0


def test_every_unmapped_sku_is_reported(data_health):
    catalog = load_catalog()
    rows = data_health[data_health.check_name == "unmapped_sku"]

    assert set(rows.subject) == set(catalog.loc[~catalog.in_crosswalk, "partner_sku"])


def test_duplicate_rate_is_near_the_planted_rate(connection, data_health, truth):
    removed = data_health.loc[data_health.check_name == "duplicate_lines", "row_count"].iloc[0]
    kept = connection.execute("select count(*) from staging.stg_vault__order_lines").fetchone()[0]

    assert removed / kept == pytest.approx(truth["mess"]["vault"]["duplicate_order_rate"], rel=0.25)


def test_unknown_region_rate_is_near_the_planted_rate(connection, data_health, truth):
    unknown = data_health.loc[data_health.check_name == "unknown_region", "row_count"].iloc[0]
    rows = connection.execute("select count(*) from staging.stg_toyworks__sales").fetchone()[0]

    assert unknown / rows == pytest.approx(truth["mess"]["toyworks"]["blank_region_rate"], rel=0.25)


def test_every_mart_and_column_is_documented(connection):
    models = yaml.safe_load((MARTS_DIR / "_marts.yml").read_text())["models"]
    documented = {model["name"]: model for model in models}
    tables = connection.execute(
        "select table_name, column_name from information_schema.columns "
        "where table_schema = 'marts'"
    ).df()

    assert set(tables.table_name) == set(documented)
    for table, columns in tables.groupby("table_name"):
        model = documented[table]
        descriptions = {
            column["name"]: column.get("description") for column in model["columns"]
        }
        assert model.get("description"), table
        for column in columns.column_name:
            assert descriptions.get(column), f"{table}.{column} has no description"
