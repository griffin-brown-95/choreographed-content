# Fandom Ledger — Project Spec

> Turning messy licensing-partner sales data and real fan buzz into one trusted source of truth, explored in a Plotly Dash app.

## 1. Overview

Fandom Ledger is a portfolio project that mimics the work of an analytics engineer supporting a streaming company's Consumer Products (licensing & merchandise) team.

The core business question:

> **When a title launches, does fan buzz predict merch sales — and which partners and regions convert buzz into sales best?**

Three licensing partners send sales reports in different, messy formats. Real daily Wikipedia pageviews serve as the "fan buzz" signal. dbt unifies everything into tested marts, and a Plotly Dash app presents the results, including a data-health page.

**Data honesty:** Title names, launch dates, pageviews, and FX rates are real. **All sales and order data is synthetic.** This must be stated in the README and on a banner in the Dash app.

## 2. Goals and non-goals

### Goals
- Demonstrate turning heterogeneous, messy sources into a clean, tested dimensional model with dbt.
- Demonstrate entity resolution (partner SKUs → titles) with visible handling of unmapped records.
- Ship a multi-page Plotly Dash app a non-technical stakeholder could use.
- Engineering hygiene: version control, tests, CI, reproducible local setup.
- Phase 2: add a Kafka event stream landing in Iceberg, joined into the same marts.

### Non-goals
- No cloud warehouse or cloud deployment (everything runs locally).
- No ML models or forecasting in v1.
- No authentication on the Dash app.
- No real merchandise data of any kind.

## 3. Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Package/env management | `uv` |
| Warehouse | DuckDB (single file: `data/fandom_ledger.duckdb`) |
| Transformation | dbt-core + `dbt-duckdb` |
| App | Plotly Dash (multi-page via `dash.register_page`) + Plotly Express |
| Excel handling | `openpyxl` |
| HTTP | `httpx` |
| Lint/format | `ruff` |
| Tests (Python) | `pytest` |
| CI | GitHub Actions |
| Phase 2 | Kafka (Docker, single broker, KRaft mode), `confluent-kafka`, PyIceberg (`SqlCatalog` on SQLite + local warehouse dir), DuckDB `iceberg` extension |

## 4. Repository layout

```
fandom-ledger/
├── README.md
├── spec.md
├── Makefile
├── pyproject.toml
├── .github/workflows/ci.yml
├── config/
│   └── ground_truth.yml          # planted effects the generator uses (see §5.3)
├── data/
│   ├── raw/                      # generated + downloaded files (gitignored)
│   │   ├── partner_a/            # CSVs
│   │   ├── partner_b/            # XLSX (incl. restatements)
│   │   ├── partner_c/            # JSON
│   │   ├── pageviews/
│   │   └── fx/
│   ├── fixtures/                 # small committed samples for CI (no network)
│   └── fandom_ledger.duckdb      # gitignored
├── ingest/
│   ├── fetch_pageviews.py
│   ├── fetch_fx.py
│   ├── generate_partner_data.py
│   └── load_raw.py               # loads data/raw/* into DuckDB `raw` schema
├── streaming/                    # Phase 2
│   ├── docker-compose.yml
│   ├── produce_orders.py
│   └── consume_to_iceberg.py
├── dbt/fandom_ledger/
│   ├── dbt_project.yml
│   ├── profiles.yml              # project-local profile pointing at the DuckDB file
│   ├── seeds/
│   ├── models/{staging,intermediate,marts}/
│   ├── tests/
│   └── macros/
├── app/
│   ├── app.py
│   ├── db.py                     # read-only DuckDB connection helper
│   └── pages/{title_explorer,partner_scorecard,data_health}.py
└── tests/                        # pytest for ingest + generator
```

## 5. Data sources

### 5.1 Titles (seed: `seeds/titles.csv`)

Columns: `title_id, title_name, wikipedia_article, title_type, launch_date, season_label`.

Starter list (one row per launch; a title can have multiple seasons). **Verify every `wikipedia_article` and `launch_date` against Wikipedia before committing.**

| title_name | wikipedia_article | launch (verify) |
|---|---|---|
| Stranger Things | `Stranger_Things` | S5 Vol. 1: 2025-11-26 |
| Wednesday | `Wednesday_(TV_series)` | S1: 2022-11-23; S2 Pt 1: 2025-08-06 |
| Squid Game | `Squid_Game` | S2: 2024-12-26; S3: 2025-06-27 |
| Arcane | `Arcane_(TV_series)` | S2 Act 1: 2024-11-09 |
| One Piece (live action) | `One_Piece_(2023_TV_series)` | S1: 2023-08-31 |
| KPop Demon Hunters | `KPop_Demon_Hunters` | 2025-06-20 |
| Bridgerton | `Bridgerton` | S3 Pt 1: 2024-05-16 |

**Date window:** 2022-10-01 through the most recent complete month.

### 5.2 Real sources

**Wikipedia pageviews** (`ingest/fetch_pageviews.py`)
- Endpoint: `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{article}/daily/{YYYYMMDD}/{YYYYMMDD}`
- Must send a descriptive `User-Agent` header (Wikimedia requirement).
- Save one JSON file per article to `data/raw/pageviews/`.
- Handle gaps (missing days) and 404s gracefully; log, don't crash.

**FX rates** (`ingest/fetch_fx.py`)
- Frankfurter API (free, no key): EUR→USD and GBP→USD daily for the date window.
- No rates are published on weekends/holidays; leave the gaps in raw data. Forward-filling happens in dbt.

### 5.3 Synthetic partner data (`ingest/generate_partner_data.py`)

The generator must be **deterministic** (fixed random seed) and must **read the real pageviews** so sales are correlated with buzz. Effects are planted from `config/ground_truth.yml` so the marts can be checked against a known answer.

**Sales model (per title × partner × region × day):**
- `units = base_demand × partner_factor × region_factor × f(lagged pageviews) + noise`
- Buzz response lags pageviews by a partner-specific number of days (e.g. apparel faster than toys).
- Planted findings in `ground_truth.yml`, for example:
  - Partner B converts buzz to sales best in EU.
  - Partner C has the strongest response for anime/animated titles (Arcane, One Piece, KPop Demon Hunters).
  - One title has high buzz but weak merch conversion.

**Partner A — "Toyworks" (toys, US/CA)**
- Monthly CSV: `data/raw/partner_a/toyworks_sales_YYYY_MM.csv`
- Columns: `Sales Date` (MM/DD/YYYY), `Item #`, `Item Desc`, `Region`, `Units Sold`, `Sales Amt` (USD, with `$` and commas as strings, e.g. `"$1,234.50"`)
- Mess: trailing whitespace in `Item #`; ~1% of rows have a blank `Region`; one month arrives late (file date after the next month's file).

**Partner B — "Maison Merch" (apparel, EU/UK)**
- Monthly XLSX: `data/raw/partner_b/maison_merch_YYYYMM.xlsx`
- Two merged title rows above the real header; header in French-ish English (`Date Vente`, `Ref Article`, `Pays`, `Qte`, `CA Net`, `Devise`)
- Dates DD.MM.YYYY; currency EUR or GBP by country; decimal comma in amounts.
- Mess: **restatements** — for ~3 months, a `_v2` file is sent later with corrected figures. Only the latest version per month should count.

**Partner C — "Vault Collectibles" (games/collectibles, global)**
- Weekly JSON "API dumps": `data/raw/partner_c/vault_export_YYYY-WW.json`
- Nested: `{ "export_id", "generated_at", "orders": [ { "order_ref", "date" (ISO 8601 with timezone), "country_iso2", "lines": [ { "vault_sku", "qty", "unit_price_usd" } ] } ] }`
- Mess: ~2% duplicated orders across overlapping weekly exports; SKU codes use Partner C's own scheme.

**SKU crosswalk (seed: `seeds/sku_crosswalk.csv`)**
- Columns: `partner_id, partner_sku, title_id, product_category`
- Deliberately **incomplete**: ~3% of partner SKUs have no mapping, so the data-health page has something real to show.

**Other seeds:** `partners.csv`, `regions.csv` (country → region mapping, including the inconsistent codes each partner uses, e.g. `UK` vs `GB`).

## 6. dbt project

### 6.1 Sources
`raw` schema in DuckDB: one table per source, loaded by `ingest/load_raw.py` with `_loaded_at` and `_source_file` columns on every row.

### 6.2 Staging (one model per source; rename, cast, standardize — no joins)
- `stg_toyworks__sales`
- `stg_maison_merch__sales` (parse decimal comma, keep `_source_file` to derive restatement version)
- `stg_vault__order_lines` (unnest JSON, dedupe on `order_ref` + line, normalize timestamp to UTC date)
- `stg_wikipedia__pageviews`
- `stg_frankfurter__fx_rates`

All staging models output a common shape where applicable: `partner_id, sale_date, partner_sku, country_code, units, gross_amount, currency_code`.

### 6.3 Intermediate
- `int_fx_rates_daily` — one row per currency per calendar day, weekends/holidays forward-filled.
- `int_maison_merch__latest_restatement` — keep only the latest file version per month.
- `int_partner_sales_unioned` — union of the three partners in the common shape.
- `int_partner_sales_mapped` — joined to the SKU crosswalk; adds `is_mapped`; converts to USD.

### 6.4 Marts
- `dim_titles`, `dim_partners`, `dim_regions`
- `fct_merch_sales_daily` — grain: title × partner × region × day; mapped rows only.
- `fct_title_buzz_daily` — grain: title × day.
- `mart_title_launch_performance` — buzz and sales indexed to days-since-launch (−30 to +90), per title/season.
- `mart_partner_conversion` — sales per 1,000 pageviews by partner × region × title.
- `mart_data_health` — unmapped SKU counts and revenue, late files, restatement deltas, duplicate counts removed.

### 6.5 Tests
- Generic: `unique`, `not_null` on all keys; `relationships` from facts to dims; `accepted_values` for `currency_code` and `region`.
- Custom singular/generic tests:
  - Unmapped SKU revenue share must be below 5% (warn at 2%).
  - No duplicate Vault order lines after staging.
  - Exactly one restatement version per Maison Merch month in intermediate.
  - Every day in the window has an FX rate for each currency after forward-fill.
- Model descriptions and column docs for every mart; `dbt docs generate` must succeed.

## 7. Dash app

Multi-page app reading marts from DuckDB in **read-only** mode. A persistent banner states: *"Sales figures are synthetic. Title buzz data is real (Wikipedia pageviews)."*

**Page 1 — Title Explorer**
- Controls: title/season dropdown, date range.
- Dual-axis chart: daily pageviews and daily merch revenue, with the launch date marked.
- KPI cards: total revenue, peak buzz day, days from launch to peak sales.

**Page 2 — Partner Scorecard**
- Heatmap: sales per 1,000 pageviews by partner × region.
- Bar chart: conversion by title for the selected partner.
- Table: underlying numbers, sortable.

**Page 3 — Data Health**
- Unmapped SKUs: count, revenue at risk, list of top unmapped SKUs by partner.
- Restatements: original vs restated revenue per month.
- Late files and duplicates removed.

Use callbacks (not global reruns); keep queries in `app/db.py` as named functions.

## 8. Phase 2 — Kafka shop orders

Adds a direct-to-consumer "shop" channel as an event stream.

- `streaming/docker-compose.yml`: single Kafka broker in KRaft mode.
- Topic `shop_orders`, 3 partitions, keyed by `customer_session_id`.
- `produce_orders.py`: synthetic order events (`event_id`, `event_ts`, `customer_session_id`, `title_id`, `sku`, `qty`, `unit_price_usd`, `country_code`), volume driven by the same buzz model. ~2% of events arrive late or out of order.
- `consume_to_iceberg.py`: batch every 500 events or 30 seconds → PyIceberg append to `shop.orders` (partitioned by `day(event_ts)`). Store the last committed Kafka offsets per partition in the Iceberg snapshot summary properties and resume from them on startup (exactly-once into Iceberg).
- dbt: `stg_shop__orders` reads the Iceberg table via DuckDB `iceberg_scan`; dedupe on `event_id`; shop becomes a fourth "partner" (`partner_id = 'shop'`) in `int_partner_sales_unioned`.
- Fallback if DuckDB/Iceberg compatibility is a problem: document the issue and have the consumer also write Parquet, which dbt reads instead.

## 9. Tooling, Makefile, CI

**Makefile targets**
- `make setup` — `uv sync`, `dbt deps`
- `make fetch` — pageviews + FX (network)
- `make generate` — synthetic partner files
- `make load` — raw files → DuckDB
- `make build` — `dbt build` (seeds, models, tests)
- `make app` — run Dash locally
- `make all` — fetch → generate → load → build
- `make ci` — same as `all` but uses `data/fixtures/` instead of the network

**CI (`.github/workflows/ci.yml`)** on every PR: `ruff check`, `pytest`, then `make ci` (dbt build against fixtures). **CI must never call external APIs.**

## 10. Milestones and acceptance criteria

**M1 — Ingest**
- Pageviews and FX fetched for all titles and the full window.
- Generator produces all partner files with every listed type of mess; same seed gives byte-identical output.
- `load_raw.py` loads everything into the `raw` schema.
- pytest covers generator determinism and each partner's mess features.

**M2 — dbt**
- All staging, intermediate, and mart models build; all tests pass.
- `mart_partner_conversion` recovers the planted findings in `ground_truth.yml` (add a pytest or dbt test that checks this).
- `dbt docs generate` succeeds.

**M3 — Dash**
- All three pages work, with the synthetic-data banner.
- App starts with `make app` against a freshly built DuckDB file.

**M4 — CI and README**
- CI green on a PR.
- README: the business question, architecture diagram, how to run, the data-honesty note, screenshots, and 3–5 findings written as a short stakeholder memo.

**M5 — Kafka (Phase 2)**
- Producer → Kafka → Iceberg working via docker compose.
- Killing the consumer mid-batch and restarting produces no duplicates in Iceberg.
- Shop channel appears in the marts and the Dash app.

## 11. Working notes for Claude Code

- Work one milestone at a time; stop after each for review.
- Ask before adding dependencies not listed in §3.
- Keep SQL in dbt; Python only for ingest, generation, streaming, and the app.
- SQL style: lowercase keywords, CTEs over subqueries, one model per file, `snake_case`.
- Never commit anything in `data/raw/` or the DuckDB file; do commit `data/fixtures/`.
- When a source behaves differently than this spec says (e.g. an API response shape), update this spec in the same change.
