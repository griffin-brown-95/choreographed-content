export FANDOM_LEDGER_DB := $(CURDIR)/data/fandom_ledger.duckdb
export DBT_PROJECT_DIR := $(CURDIR)/dbt/fandom_ledger
export DBT_PROFILES_DIR := $(CURDIR)/dbt/fandom_ledger

.PHONY: setup lint test fetch build

setup:
	uv sync
	uv run dbt deps

lint:
	uv run ruff check .

test:
	uv run pytest

fetch:
	uv run python -m ingest.fetch_pageviews
	uv run python -m ingest.fetch_fx

build:
	uv run dbt build
