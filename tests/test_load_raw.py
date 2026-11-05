"""Loader tests. They load generated fixture data into a temporary DuckDB file."""

import csv
import json
import shutil
from pathlib import Path

import duckdb
import pytest
from openpyxl import load_workbook

from ingest.load_raw import READERS, load


@pytest.fixture(scope="module")
def db_path(raw_dir, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("db") / "test.duckdb"
    load(raw_dir, path)
    return path


@pytest.fixture(scope="module")
def connection(db_path):
    with duckdb.connect(str(db_path), read_only=True) as read_only_connection:
        yield read_only_connection


def scalar(connection, sql: str):
    return connection.execute(sql).fetchone()[0]


def test_every_source_has_a_table(connection):
    tables = connection.execute(
        "select table_name from information_schema.tables where table_schema = 'raw'"
    ).fetchall()
    assert {table for (table,) in tables} == set(READERS)


@pytest.mark.parametrize("table", READERS)
def test_every_row_has_load_metadata(connection, table):
    missing = scalar(
        connection,
        f"""
        select count(*) from raw.{table}
        where _loaded_at is null or _source_file is null or _source_file = ''
        """,
    )
    assert missing == 0
    assert scalar(connection, f"select count(*) from raw.{table}") > 0


@pytest.mark.parametrize("table", READERS)
def test_source_columns_stay_as_text(connection, table):
    types = connection.execute(
        f"""
        select column_name, data_type from information_schema.columns
        where table_schema = 'raw' and table_name = '{table}' and column_name != '_loaded_at'
        """
    ).fetchall()
    assert {data_type for _, data_type in types} == {"VARCHAR"}


def test_toyworks_row_count_matches_the_files(connection, raw_dir):
    expected = 0
    for path in (raw_dir / "partner_a").glob("*.csv"):
        with path.open(newline="") as file:
            expected += sum(1 for _ in csv.DictReader(file))
    assert scalar(connection, "select count(*) from raw.toyworks_sales") == expected


def test_toyworks_mess_is_preserved(connection):
    padded = scalar(
        connection,
        """select count(*) from raw.toyworks_sales where "Item #" != rtrim("Item #")""",
    )
    blank = scalar(connection, """select count(*) from raw.toyworks_sales where "Region" = ''""")
    amounts = scalar(
        connection,
        """select count(*) from raw.toyworks_sales where "Sales Amt" not like '$%'""",
    )
    assert padded > 0
    assert blank > 0
    assert amounts == 0


def test_maison_keeps_both_restatement_versions(connection, raw_dir):
    expected = {path.name for path in (raw_dir / "partner_b").glob("*.xlsx")}
    files = connection.execute(
        "select distinct _source_file from raw.maison_merch_sales"
    ).fetchall()
    assert {name for (name,) in files} == expected
    assert any("_v2" in name for name in expected)


def test_maison_row_count_matches_the_files(connection, raw_dir):
    expected = 0
    for path in (raw_dir / "partner_b").glob("*.xlsx"):
        expected += load_workbook(path, read_only=True).active.max_row - 3
    assert scalar(connection, "select count(*) from raw.maison_merch_sales") == expected


def test_maison_mess_is_preserved(connection):
    without_comma = scalar(
        connection,
        """select count(*) from raw.maison_merch_sales where "CA Net" not like '%,%'""",
    )
    wrong_dates = scalar(
        connection,
        """
        select count(*) from raw.maison_merch_sales
        where not regexp_full_match("Date Vente", '\\d{2}\\.\\d{2}\\.\\d{4}')
        """,
    )
    assert without_comma == 0
    assert wrong_dates == 0


def test_vault_duplicates_survive_and_orders_can_be_unnested_in_sql(connection, raw_dir):
    orders = []
    for path in (raw_dir / "partner_c").glob("*.json"):
        orders.extend(json.loads(path.read_text())["orders"])

    loaded = scalar(
        connection,
        "select sum(json_array_length(orders::json)) from raw.vault_exports",
    )
    unique_refs = scalar(
        connection,
        """
        with orders as (
            select unnest(from_json(orders::json, '["json"]')) as order_json
            from raw.vault_exports
        )
        select count(distinct order_json ->> 'order_ref') from orders
        """,
    )
    assert loaded == len(orders)
    assert unique_refs == len({order["order_ref"] for order in orders})
    assert unique_refs < loaded


def test_pageviews_and_fx_keep_their_real_gaps(connection):
    first_day = scalar(
        connection,
        """
        select min(timestamp) from raw.wikipedia_pageviews
        where article = 'KPop_Demon_Hunters'
        """,
    )
    saturdays = scalar(
        connection,
        """
        select count(*) from raw.frankfurter_fx_rates
        where dayofweek(rate_date::date) in (0, 6)
        """,
    )
    assert first_day.startswith("20250424")
    assert saturdays == 0


def test_reloading_replaces_rows(raw_dir, tmp_path):
    path = tmp_path / "reload.duckdb"
    first = load(raw_dir, path)
    second = load(raw_dir, path)

    assert first == second
    with duckdb.connect(str(path), read_only=True) as connection:
        rows = scalar(connection, "select count(*) from raw.delivery_manifest")
    assert rows == first["delivery_manifest"]


def test_load_leaves_other_schemas_alone(raw_dir, tmp_path):
    path = tmp_path / "other.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("create schema seeds")
        connection.execute("create table seeds.keep_me as select 1 as id")

    load(raw_dir, path)

    with duckdb.connect(str(path), read_only=True) as connection:
        assert scalar(connection, "select count(*) from seeds.keep_me") == 1


def test_missing_source_fails_before_touching_the_database(raw_dir, tmp_path):
    path = tmp_path / "failed.duckdb"
    load(raw_dir, path)
    with duckdb.connect(str(path), read_only=True) as connection:
        loaded_at = scalar(connection, "select max(_loaded_at) from raw.toyworks_sales")

    broken = tmp_path / "raw"
    shutil.copytree(raw_dir, broken)
    shutil.rmtree(broken / "partner_c")
    with pytest.raises(FileNotFoundError):
        load(broken, path)

    with duckdb.connect(str(path), read_only=True) as connection:
        assert scalar(connection, "select max(_loaded_at) from raw.toyworks_sales") == loaded_at


def test_unexpected_maison_header_is_rejected(raw_dir, tmp_path):
    broken = tmp_path / "raw"
    shutil.copytree(raw_dir, broken)
    path = sorted((broken / "partner_b").glob("*.xlsx"))[0]
    workbook = load_workbook(path)
    workbook.active["A3"] = "Date"
    workbook.save(path)

    with pytest.raises(ValueError, match="unexpected header"):
        load(broken, tmp_path / "bad.duckdb")
