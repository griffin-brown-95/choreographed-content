export FANDOM_LEDGER_DB := $(CURDIR)/data/fandom_ledger.duckdb
export DBT_PROJECT_DIR := $(CURDIR)/dbt/fandom_ledger
export DBT_PROFILES_DIR := $(CURDIR)/dbt/fandom_ledger

.PHONY: setup lint test fetch fixtures generate load build all ci

setup:
	uv sync --locked
	uv run dbt deps

lint:
	uv run ruff check .

test:
	uv run pytest

fetch:
	uv run python -m ingest.fetch_pageviews
	uv run python -m ingest.fetch_fx

fixtures:
	uv run python -m ingest.fixtures snapshot

generate:
	uv run python -m ingest.generate_partner_data

load:
	uv run python -m ingest.load_raw

build:
	uv run dbt build

all: fetch generate load build

ci:
	uv run python -m ingest.fixtures restore
	$(MAKE) generate load build
