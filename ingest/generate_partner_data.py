"""Generate deterministic synthetic partner files from real pageviews.

Sales come from config/ground_truth.yml and config/sku_catalog.csv. Each partner's
file format and mess is added afterwards, using separate random streams, so changing
the mess never changes the underlying sales.
"""

import csv
import io
import json
import logging
import re
import shutil
import sys
import zipfile
from datetime import UTC, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from openpyxl import Workbook

from ingest.common import (
    RAW_DIR,
    ROOT,
    SEEDS_DIR,
    configure_logging,
    load_pipeline_config,
)

PARTNER_DIRS = {"toyworks": "partner_a", "maison_merch": "partner_b", "vault": "partner_c"}
MANIFEST_NAME = "delivery_manifest.csv"

# Workbooks embed save times. Fixing them keeps the same seed byte-identical.
FIXED_ZIP_TIME = (2000, 1, 1, 0, 0, 0)
FIXED_XML_TIME = b"2000-01-01T00:00:00Z"

logger = logging.getLogger(__name__)


def load_ground_truth() -> dict:
    return yaml.safe_load((ROOT / "config" / "ground_truth.yml").read_text())


def load_catalog() -> pd.DataFrame:
    return pd.read_csv(ROOT / "config" / "sku_catalog.csv", keep_default_na=False)


def load_titles() -> pd.DataFrame:
    return pd.read_csv(SEEDS_DIR / "titles.csv", parse_dates=["first_sale_date"])


def load_raw_country_codes() -> dict[tuple[str, str], str]:
    """Map (partner_id, standard country code) to the code that partner reports."""
    regions = pd.read_csv(SEEDS_DIR / "regions.csv", keep_default_na=False)
    return {
        (row.partner_id, row.country_code): row.raw_country_code
        for row in regions.itertuples()
    }


def load_pageviews(pageviews_dir: Path, article: str) -> pd.Series:
    items = json.loads((pageviews_dir / f"{article}.json").read_text())["items"]
    dates = pd.to_datetime([item["timestamp"][:8] for item in items], format="%Y%m%d")
    return pd.Series([item["views"] for item in items], index=dates, dtype=float)


def demand_factor(truth: dict, partner_id: str, region: str, title) -> float:
    """Combine every factor and planted multiplier for one partner, region, and title."""
    effects = truth["planted_effects"]
    factor = (
        truth["base_demand"]
        * truth["partners"][partner_id]["partner_factor"]
        * truth["region_factors"][region]
    )
    for effect in effects["partner_region"]:
        if effect["partner"] == partner_id and effect["region"] == region:
            factor *= effect["multiplier"]
    for effect in effects["partner_segment"]:
        if effect["partner"] == partner_id and effect["fan_segment"] == title.fan_segment:
            factor *= effect["multiplier"]
    for effect in effects["title"]:
        if effect["title"] == title.title_id:
            factor *= effect["multiplier"]
    return factor


def simulate_sales(
    truth: dict,
    titles: pd.DataFrame,
    catalog: pd.DataFrame,
    pageviews_dir: Path,
    window_end: pd.Timestamp,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Return one row per day, partner SKU, and country with at least one unit sold."""
    dispersion = truth["noise_dispersion"]
    frames = []
    for partner_id, partner in truth["partners"].items():
        for title in titles.itertuples():
            is_match = (catalog.partner_id == partner_id) & (catalog.title_id == title.title_id)
            skus = catalog[is_match]
            if skus.empty:
                continue
            days = pd.date_range(title.first_sale_date, window_end)
            views = load_pageviews(pageviews_dir, title.wikipedia_article)
            lagged = views.shift(partner["lag_days"], freq="D").reindex(days).fillna(0).to_numpy()
            sku_weights = (skus.demand_weight / skus.demand_weight.sum()).to_numpy()

            for region in partner["regions"]:
                factor = demand_factor(truth, partner_id, region, title)
                # One shock per title, partner, region, and day, shared by that day's SKUs.
                shock = rng.gamma(1 / dispersion, dispersion, len(days))
                countries = truth["country_weights"][region]
                country_weights = np.array(list(countries.values()))
                rates = (
                    (lagged / 1000 * factor * shock)[:, None, None]
                    * sku_weights[None, :, None]
                    * country_weights[None, None, :]
                )
                units = rng.poisson(rates)
                day_index, sku_index, country_index = np.nonzero(units)
                frames.append(
                    pd.DataFrame(
                        {
                            "sale_date": days[day_index],
                            "partner_id": partner_id,
                            "partner_sku": skus.partner_sku.to_numpy()[sku_index],
                            "country_code": np.array(list(countries))[country_index],
                            "units": units[day_index, sku_index, country_index],
                        }
                    )
                )

    sales = pd.concat(frames, ignore_index=True)
    details = catalog[["partner_id", "partner_sku", "item_description", "list_price"]]
    sales = sales.merge(details, on=["partner_id", "partner_sku"], validate="many_to_one")
    sort_columns = ["sale_date", "partner_sku", "country_code"]
    return sales.sort_values(sort_columns, ignore_index=True)


def delivered_at(month_end: pd.Timestamp, days_after: int) -> datetime:
    day = (month_end + pd.Timedelta(days=days_after)).date()
    return datetime.combine(day, time(9), tzinfo=UTC)


def manifest_row(partner_id: str, path: Path, period: str, delivered: datetime) -> dict:
    return {
        "partner_id": partner_id,
        "file_name": path.name,
        "period": period,
        "delivered_at": delivered.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def write_toyworks(
    sales: pd.DataFrame,
    mess: dict,
    raw_codes: dict,
    out_dir: Path,
    rng: np.random.Generator,
) -> list[dict]:
    rows = sales[sales.partner_id == "toyworks"]
    manifest = []
    for month, month_rows in rows.groupby(rows.sale_date.dt.to_period("M")):
        path = out_dir / f"toyworks_sales_{month.year}_{month.month:02d}.csv"
        blank_region = rng.random(len(month_rows)) < mess["blank_region_rate"]
        padded_sku = rng.random(len(month_rows)) < mess["trailing_whitespace_rate"]

        with path.open("w", newline="") as file:
            writer = csv.writer(file, lineterminator="\n")
            writer.writerow(
                ["Sales Date", "Item #", "Item Desc", "Region", "Units Sold", "Sales Amt"]
            )
            for row, is_blank, is_padded in zip(
                month_rows.itertuples(), blank_region, padded_sku, strict=True
            ):
                writer.writerow(
                    [
                        row.sale_date.strftime("%m/%d/%Y"),
                        row.partner_sku + ("   " if is_padded else ""),
                        row.item_description,
                        "" if is_blank else raw_codes["toyworks", row.country_code],
                        row.units,
                        f"${row.units * row.list_price:,.2f}",
                    ]
                )

        is_late = str(month) == mess["late_month"]
        days_after = mess["late_days"] if is_late else mess["on_time_days"]
        delivered = delivered_at(month.end_time.normalize(), days_after)
        manifest.append(manifest_row("toyworks", path, str(month), delivered))
    return manifest


def save_normalized_workbook(workbook: Workbook, path: Path) -> None:
    """Save a workbook with fixed timestamps, so identical content gives identical bytes."""
    buffer = io.BytesIO()
    workbook.save(buffer)
    with (
        zipfile.ZipFile(buffer) as source,
        zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "docProps/core.xml":
                content = re.sub(
                    rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*",
                    rb"\g<1>" + FIXED_XML_TIME,
                    content,
                )
            info = zipfile.ZipInfo(item.filename, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, content)


def write_maison_workbook(
    rows: pd.DataFrame,
    month: pd.Period,
    mess: dict,
    raw_codes: dict,
    path: Path,
    revenue_factor: float = 1.0,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Ventes"
    sheet.append(["MAISON MERCH - RAPPORT DE VENTES"])
    sheet.append([f"Periode: {month}"])
    sheet.merge_cells("A1:F1")
    sheet.merge_cells("A2:F2")
    sheet.append(["Date Vente", "Ref Article", "Pays", "Qte", "CA Net", "Devise"])
    for row in rows.itertuples():
        is_uk = row.country_code == "GB"
        price = row.list_price * mess["gbp_per_eur"] if is_uk else row.list_price
        amount = row.units * price * revenue_factor
        sheet.append(
            [
                row.sale_date.strftime("%d.%m.%Y"),
                row.partner_sku,
                raw_codes["maison_merch", row.country_code],
                row.units,
                f"{amount:.2f}".replace(".", ","),
                "GBP" if is_uk else "EUR",
            ]
        )
    save_normalized_workbook(workbook, path)


def write_maison_merch(
    sales: pd.DataFrame, mess: dict, raw_codes: dict, out_dir: Path
) -> list[dict]:
    rows = sales[sales.partner_id == "maison_merch"]
    restatements = {item["month"]: item["v1_revenue_factor"] for item in mess["restatements"]}
    manifest = []
    for month, month_rows in rows.groupby(rows.sale_date.dt.to_period("M")):
        month_end = month.end_time.normalize()
        stem = f"maison_merch_{month.year}{month.month:02d}"
        first_version = out_dir / f"{stem}.xlsx"
        write_maison_workbook(
            month_rows,
            month,
            mess,
            raw_codes,
            first_version,
            revenue_factor=restatements.get(str(month), 1.0),
        )
        delivered = delivered_at(month_end, mess["on_time_days"])
        manifest.append(manifest_row("maison_merch", first_version, str(month), delivered))

        if str(month) in restatements:
            second_version = out_dir / f"{stem}_v2.xlsx"
            write_maison_workbook(month_rows, month, mess, raw_codes, second_version)
            delivered = delivered_at(month_end, mess["restatement_days"])
            manifest.append(manifest_row("maison_merch", second_version, str(month), delivered))
    return manifest


def build_vault_orders(
    sales: pd.DataFrame, mess: dict, raw_codes: dict, rng: np.random.Generator
) -> list[dict]:
    """Group Vault's daily sales into orders, each from one country on one UTC day."""
    rows = sales[sales.partner_id == "vault"]
    orders = []

    def close_order(lines: list[dict], sale_date: pd.Timestamp, country: str) -> None:
        offset = timezone(timedelta(hours=mess["utc_offset_hours"][country]))
        seconds = int(rng.integers(0, 86_400))
        ordered_at = sale_date.to_pydatetime().replace(tzinfo=UTC) + timedelta(seconds=seconds)
        orders.append(
            {
                "order_ref": f"VO-{len(orders) + 1:08d}",
                "date": ordered_at.astimezone(offset).isoformat(),
                "country_iso2": raw_codes["vault", country],
                "lines": lines,
                "_utc_day": sale_date,
            }
        )

    for (sale_date, country), day_rows in rows.groupby(["sale_date", "country_code"]):
        lines = []
        for row in day_rows.itertuples():
            remaining = int(row.units)
            while remaining:
                quantity = min(remaining, int(rng.integers(1, mess["max_line_quantity"] + 1)))
                lines.append(
                    {
                        "vault_sku": row.partner_sku,
                        "qty": quantity,
                        "unit_price_usd": row.list_price,
                    }
                )
                remaining -= quantity

        current = []
        target_size = int(rng.integers(1, mess["max_lines_per_order"] + 1))
        for index in rng.permutation(len(lines)):
            line = lines[index]
            has_sku = any(item["vault_sku"] == line["vault_sku"] for item in current)
            if current and (has_sku or len(current) == target_size):
                close_order(current, sale_date, country)
                current = []
                target_size = int(rng.integers(1, mess["max_lines_per_order"] + 1))
            current.append(line)
        if current:
            close_order(current, sale_date, country)
    return orders


def iso_week_key(day: pd.Timestamp) -> tuple[int, int]:
    calendar = day.isocalendar()
    return calendar.year, calendar.week


def write_vault(
    sales: pd.DataFrame, mess: dict, raw_codes: dict, out_dir: Path, rng: np.random.Generator
) -> list[dict]:
    orders = build_vault_orders(sales, mess, raw_codes, rng)

    exports: dict[tuple[int, int], list[dict]] = {}
    for order in orders:
        exports.setdefault(iso_week_key(order["_utc_day"]), []).append(order)
    weeks = sorted(exports)
    next_week = dict(zip(weeks, weeks[1:], strict=False))

    # Overlapping exports repeat some orders in the following week's file.
    repeats: dict[tuple[int, int], list[dict]] = {}
    is_repeated = rng.random(len(orders)) < mess["duplicate_order_rate"]
    for order, repeated in zip(orders, is_repeated, strict=True):
        week = iso_week_key(order["_utc_day"])
        if repeated and week in next_week:
            repeats.setdefault(next_week[week], []).append(order)

    manifest = []
    for year, week in weeks:
        period = f"{year}-{week:02d}"
        week_end = pd.Timestamp(datetime.fromisocalendar(year, week, 7))
        generated_at = datetime.combine(
            (week_end + pd.Timedelta(days=1)).date(), time(6), tzinfo=UTC
        )
        contents = repeats.get((year, week), []) + exports[year, week]
        payload = {
            "export_id": f"vault-export-{period}",
            "generated_at": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "orders": [
                {key: value for key, value in order.items() if key != "_utc_day"}
                for order in contents
            ],
        }
        path = out_dir / f"vault_export_{period}.json"
        path.write_text(json.dumps(payload, indent=1) + "\n")
        manifest.append(manifest_row("vault", path, period, generated_at))
    return manifest


def write_crosswalk(catalog: pd.DataFrame, path: Path) -> None:
    columns = ["partner_id", "partner_sku", "title_id", "product_category"]
    catalog.loc[catalog.in_crosswalk, columns].to_csv(path, index=False, lineterminator="\n")


def write_manifest(manifest: list[dict], path: Path) -> None:
    columns = ["partner_id", "file_name", "period", "delivered_at"]
    ordered = pd.DataFrame(manifest, columns=columns).sort_values(["delivered_at", "file_name"])
    ordered.to_csv(path, index=False, lineterminator="\n")


def generate(raw_dir: Path, crosswalk_path: Path, truth: dict | None = None) -> pd.DataFrame:
    """Write every partner file, the manifest, and the crosswalk. Returns the true sales."""
    truth = truth or load_ground_truth()
    window_end = pd.Timestamp(load_pipeline_config()["window"]["end"])
    catalog = load_catalog()
    raw_codes = load_raw_country_codes()
    mess = truth["mess"]

    sales_rng, toyworks_rng, vault_rng = (
        np.random.default_rng(stream)
        for stream in np.random.SeedSequence(truth["seed"]).spawn(3)
    )
    sales = simulate_sales(
        truth, load_titles(), catalog, raw_dir / "pageviews", window_end, sales_rng
    )

    out_dirs = {partner: raw_dir / name for partner, name in PARTNER_DIRS.items()}
    for out_dir in out_dirs.values():
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True)

    manifest = [
        *write_toyworks(
            sales, mess["toyworks"], raw_codes, out_dirs["toyworks"], toyworks_rng
        ),
        *write_maison_merch(sales, mess["maison_merch"], raw_codes, out_dirs["maison_merch"]),
        *write_vault(sales, mess["vault"], raw_codes, out_dirs["vault"], vault_rng),
    ]
    write_manifest(manifest, raw_dir / MANIFEST_NAME)
    write_crosswalk(catalog, crosswalk_path)
    return sales


def main() -> int:
    configure_logging()
    sales = generate(RAW_DIR, SEEDS_DIR / "sku_crosswalk.csv")
    logger.info("Generated %d sales rows and %d units", len(sales), sales.units.sum())
    return 0


if __name__ == "__main__":
    sys.exit(main())
