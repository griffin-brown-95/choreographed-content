"""Generator tests. They run on the committed fixtures, so they never touch the network."""

import copy
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from ingest.common import SEEDS_DIR
from ingest.generate_partner_data import (
    MANIFEST_NAME,
    load_catalog,
    load_ground_truth,
    load_titles,
)
from tests.helpers import run_generator


@pytest.fixture(scope="session")
def truth() -> dict:
    return load_ground_truth()


@pytest.fixture(scope="session")
def manifest(raw_dir) -> pd.DataFrame:
    return pd.read_csv(raw_dir / MANIFEST_NAME, keep_default_na=False)


@pytest.fixture(scope="session")
def toyworks(raw_dir) -> list[dict]:
    rows = []
    for path in sorted((raw_dir / "partner_a").glob("*.csv")):
        with path.open(newline="") as file:
            rows.extend(csv.DictReader(file))
    return rows


@pytest.fixture(scope="session")
def vault_exports(raw_dir) -> list[dict]:
    paths = sorted((raw_dir / "partner_c").glob("*.json"))
    return [json.loads(path.read_text()) for path in paths]


@pytest.fixture(scope="session")
def vault_orders(vault_exports) -> list[dict]:
    return [order for export in vault_exports for order in export["orders"]]


def maison_rows(path: Path) -> list[tuple]:
    sheet = load_workbook(path).active
    return list(sheet.iter_rows(min_row=4, values_only=True))


def maison_revenue(path: Path) -> float:
    return sum(float(row[4].replace(",", ".")) for row in maison_rows(path) if row[5] == "EUR")


def file_hashes(raw_dir: Path) -> dict[str, str]:
    paths = [raw_dir / MANIFEST_NAME, raw_dir / "sku_crosswalk.csv"]
    for name in ("partner_a", "partner_b", "partner_c"):
        paths.extend(sorted((raw_dir / name).iterdir()))
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def test_same_seed_gives_byte_identical_files(raw_dir, tmp_path):
    run_generator(tmp_path)
    assert file_hashes(tmp_path) == file_hashes(raw_dir)


def test_different_seed_changes_the_files(raw_dir, tmp_path, truth):
    other = copy.deepcopy(truth)
    other["seed"] += 1
    run_generator(tmp_path, other)
    assert file_hashes(tmp_path) != file_hashes(raw_dir)


def test_changing_the_mess_leaves_sales_unchanged(tmp_path, truth):
    other = copy.deepcopy(truth)
    other["mess"]["vault"]["duplicate_order_rate"] = 0.1
    other["mess"]["toyworks"]["blank_region_rate"] = 0.2
    pd.testing.assert_frame_equal(
        run_generator(tmp_path / "a", truth), run_generator(tmp_path / "b", other)
    )


def test_crosswalk_output_matches_committed_seed(raw_dir):
    generated = (raw_dir / "sku_crosswalk.csv").read_text()
    assert generated == (SEEDS_DIR / "sku_crosswalk.csv").read_text()


def test_toyworks_file_names_and_columns(raw_dir, toyworks):
    names = [path.name for path in (raw_dir / "partner_a").iterdir()]
    assert all(re.fullmatch(r"toyworks_sales_\d{4}_\d{2}\.csv", name) for name in names)
    assert list(toyworks[0]) == [
        "Sales Date",
        "Item #",
        "Item Desc",
        "Region",
        "Units Sold",
        "Sales Amt",
    ]


def test_toyworks_formats_dates_and_amounts_as_strings(toyworks):
    assert all(re.fullmatch(r"\d{2}/\d{2}/\d{4}", row["Sales Date"]) for row in toyworks)
    assert all(re.fullmatch(r"\$[\d,]+\.\d{2}", row["Sales Amt"]) for row in toyworks)
    assert any("," in row["Sales Amt"] for row in toyworks)


def test_toyworks_has_trailing_whitespace_in_some_skus(toyworks):
    padded = sum(row["Item #"] != row["Item #"].rstrip() for row in toyworks)
    assert 0.05 < padded / len(toyworks) < 0.15


def test_toyworks_has_about_one_percent_blank_regions(toyworks):
    blank = sum(row["Region"] == "" for row in toyworks)
    assert 0.005 < blank / len(toyworks) < 0.015


def test_toyworks_uses_its_own_country_codes(toyworks):
    assert {row["Region"] for row in toyworks} == {"USA", "CAN", ""}


def test_toyworks_late_month_arrives_after_the_next_month(manifest, truth):
    late_month = pd.Period(truth["mess"]["toyworks"]["late_month"], "M")
    delivered = manifest[manifest.partner_id == "toyworks"].set_index("period").delivered_at
    assert delivered[str(late_month)] > delivered[str(late_month + 1)]

    in_order = delivered.drop(str(late_month))
    assert in_order.is_monotonic_increasing


def test_maison_has_merged_title_rows_above_the_header(raw_dir):
    sheet = load_workbook(raw_dir / "partner_b" / "maison_merch_202401.xlsx").active
    merged = {str(cell_range) for cell_range in sheet.merged_cells.ranges}
    assert merged == {"A1:F1", "A2:F2"}
    header = [cell.value for cell in sheet[3]]
    assert header == ["Date Vente", "Ref Article", "Pays", "Qte", "CA Net", "Devise"]


def test_maison_formats_dates_and_decimal_commas(raw_dir):
    rows = maison_rows(raw_dir / "partner_b" / "maison_merch_202401.xlsx")
    assert all(re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", row[0]) for row in rows)
    assert all(re.fullmatch(r"\d+,\d{2}", row[4]) for row in rows)


def test_maison_currency_follows_country(raw_dir):
    rows = maison_rows(raw_dir / "partner_b" / "maison_merch_202401.xlsx")
    assert {row[5] for row in rows if row[2] == "UK"} == {"GBP"}
    assert {row[5] for row in rows if row[2] != "UK"} == {"EUR"}


def test_maison_restatements_correct_the_first_version(raw_dir, truth):
    restatements = truth["mess"]["maison_merch"]["restatements"]
    versions = sorted(path.name for path in (raw_dir / "partner_b").glob("*_v2.xlsx"))
    assert len(versions) == len(restatements)

    for item in restatements:
        stem = "maison_merch_" + item["month"].replace("-", "")
        first = maison_revenue(raw_dir / "partner_b" / f"{stem}.xlsx")
        second = maison_revenue(raw_dir / "partner_b" / f"{stem}_v2.xlsx")
        assert first / second == pytest.approx(item["v1_revenue_factor"], rel=0.001)


def test_maison_restatements_arrive_after_the_first_version(manifest):
    rows = manifest[manifest.partner_id == "maison_merch"]
    for _, versions in rows.groupby("period"):
        ordered = versions.sort_values("delivered_at")
        assert ordered.file_name.iloc[-1] == max(versions.file_name, key=len)


def test_vault_exports_are_nested_as_specified(raw_dir, vault_exports):
    names = [path.name for path in (raw_dir / "partner_c").iterdir()]
    assert all(re.fullmatch(r"vault_export_\d{4}-\d{2}\.json", name) for name in names)

    export = vault_exports[0]
    assert set(export) == {"export_id", "generated_at", "orders"}
    order = export["orders"][0]
    assert set(order) == {"order_ref", "date", "country_iso2", "lines"}
    assert set(order["lines"][0]) == {"vault_sku", "qty", "unit_price_usd"}


def test_vault_has_about_two_percent_duplicate_orders(vault_orders):
    counts = Counter(order["order_ref"] for order in vault_orders)
    duplicates = sum(count - 1 for count in counts.values())
    assert 0.015 < duplicates / len(counts) < 0.025


def test_vault_duplicates_are_exact_copies_in_the_next_export(vault_exports):
    seen = {}
    repeats = 0
    for index, export in enumerate(vault_exports):
        for order in export["orders"]:
            if order["order_ref"] in seen:
                first_index, first_order = seen[order["order_ref"]]
                assert order == first_order
                assert index == first_index + 1
                repeats += 1
            else:
                seen[order["order_ref"]] = (index, order)
    assert repeats > 0


def test_vault_timestamps_have_time_zones_that_can_shift_the_date(vault_orders):
    timestamps = [datetime.fromisoformat(order["date"]) for order in vault_orders]
    assert all(timestamp.tzinfo is not None for timestamp in timestamps)
    shifted = sum(
        timestamp.date() != timestamp.astimezone(UTC).date() for timestamp in timestamps
    )
    assert shifted > 0


def test_vault_uses_gb_while_maison_uses_uk(raw_dir, vault_orders):
    assert "GB" in {order["country_iso2"] for order in vault_orders}
    assert "UK" not in {order["country_iso2"] for order in vault_orders}
    rows = maison_rows(raw_dir / "partner_b" / "maison_merch_202401.xlsx")
    assert "UK" in {row[2] for row in rows}


def test_manifest_lists_every_partner_file(raw_dir, manifest):
    files = {
        path.name
        for name in ("partner_a", "partner_b", "partner_c")
        for path in (raw_dir / name).iterdir()
    }
    assert set(manifest.file_name) == files
    assert not manifest.file_name.duplicated().any()


def test_no_sales_before_first_sale_date(sales):
    catalog = load_catalog()[["partner_id", "partner_sku", "title_id"]]
    first_sale = load_titles()[["title_id", "first_sale_date"]]
    joined = sales.merge(catalog, on=["partner_id", "partner_sku"]).merge(first_sale, on="title_id")
    assert (joined.sale_date >= joined.first_sale_date).all()


def test_unmapped_skus_are_sold(sales):
    catalog = load_catalog()
    unmapped = set(catalog.loc[~catalog.in_crosswalk, "partner_sku"])
    assert unmapped <= set(sales.partner_sku)


def test_vault_units_match_true_sales(sales, vault_orders):
    orders = {order["order_ref"]: order for order in vault_orders}
    exported = sum(line["qty"] for order in orders.values() for line in order["lines"])
    assert exported == sales.loc[sales.partner_id == "vault", "units"].sum()
