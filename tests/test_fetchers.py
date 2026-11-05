"""Fetcher tests. These use a mock transport, so they never touch the network."""

import json
import logging
from datetime import date

import httpx
import pytest

from ingest.common import USER_AGENT, get_with_retries, make_client
from ingest.fetch_fx import fetch_currency
from ingest.fetch_pageviews import fetch_article, find_missing_days, pageviews_url

START = date(2022, 10, 1)
END = date(2022, 10, 3)


def client_returning(*responses: httpx.Response) -> tuple[httpx.Client, list[httpx.Request]]:
    """Build a client that replays responses in order and records its requests."""
    requests = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return queue.pop(0)

    return make_client(httpx.MockTransport(handler)), requests


def pageview_item(day: str) -> dict:
    return {"article": "Test", "timestamp": f"{day}00", "views": 100}


def test_url_escapes_parentheses_in_article_names():
    url = pageviews_url("Arcane_(TV_series)", START, END)
    assert url.endswith("/Arcane_%28TV_series%29/daily/20221001/20221003")


def test_missing_days_are_found():
    items = [pageview_item("20221001"), pageview_item("20221003")]
    assert find_missing_days(items, START, END) == [date(2022, 10, 2)]


def test_article_is_saved_with_user_agent(tmp_path):
    payload = {"items": [pageview_item(day) for day in ("20221001", "20221002", "20221003")]}
    client, requests = client_returning(httpx.Response(200, json=payload))

    assert fetch_article(client, "Test", START, END, tmp_path)

    assert json.loads((tmp_path / "Test.json").read_text()) == payload
    assert requests[0].headers["User-Agent"] == USER_AGENT


def test_gap_is_logged_and_the_file_is_still_saved(tmp_path, caplog):
    payload = {"items": [pageview_item("20221001")]}
    client, _ = client_returning(httpx.Response(200, json=payload))

    with caplog.at_level(logging.WARNING):
        assert fetch_article(client, "Test", START, END, tmp_path)

    assert "2 missing" in caplog.text
    assert (tmp_path / "Test.json").exists()


def test_404_is_logged_and_skipped(tmp_path, caplog):
    client, _ = client_returning(httpx.Response(404, json={"title": "Not found."}))

    with caplog.at_level(logging.WARNING):
        assert fetch_article(client, "Test", START, END, tmp_path)

    assert "404" in caplog.text
    assert not (tmp_path / "Test.json").exists()


def test_persistent_server_error_is_reported_without_crashing(tmp_path):
    client, requests = client_returning(*[httpx.Response(503) for _ in range(4)])

    assert not fetch_article(client, "Test", START, END, tmp_path, backoff_seconds=0)

    assert len(requests) == 4
    assert not (tmp_path / "Test.json").exists()


def test_rate_limit_is_retried():
    client, requests = client_returning(httpx.Response(429), httpx.Response(200, json={}))

    response = get_with_retries(client, "https://example.test", backoff_seconds=0)

    assert response.status_code == 200
    assert len(requests) == 2


def test_fx_rates_are_saved_with_gaps_left_in(tmp_path):
    payload = {"base": "EUR", "rates": {"2022-09-30": {"USD": 0.98}, "2022-10-03": {"USD": 0.98}}}
    client, requests = client_returning(httpx.Response(200, json=payload))

    fetch_currency(client, "EUR", date(2022, 9, 26), START, END, tmp_path)

    assert json.loads((tmp_path / "EUR_USD.json").read_text()) == payload
    assert requests[0].url.path == "/v1/2022-09-26..2022-10-03"
    assert requests[0].url.params["base"] == "EUR"


def test_fx_fails_without_a_rate_to_forward_fill_from(tmp_path):
    payload = {"base": "EUR", "rates": {"2022-10-03": {"USD": 0.98}}}
    client, _ = client_returning(httpx.Response(200, json=payload))

    with pytest.raises(ValueError, match="forward-fill"):
        fetch_currency(client, "EUR", date(2022, 9, 26), START, END, tmp_path)

    assert not (tmp_path / "EUR_USD.json").exists()
