"""Offline tests for The Muse connector and the search orchestrator."""

from __future__ import annotations

import httpx

from jobfinder.connectors import TheMuseConnector
from jobfinder.pipeline import SearchFilters, search

_PAGE = {
    "page_count": 1,
    "results": [
        {
            "id": 1,
            "name": "Backend Engineer",
            "company": {"name": "Acme"},
            "locations": [{"name": "London, United Kingdom"}],
            "refs": {"landing_page": "https://muse/1"},
            "publication_date": "2025-02-01T10:00:00Z",
            "contents": "<p>Build services.</p>",
        },
        {
            "id": 2,
            "name": "Data Scientist",
            "company": {"name": "Acme"},
            "locations": [{"name": "Berlin, Germany"}],
            "refs": {"landing_page": "https://muse/2"},
            "publication_date": "2025-02-02T10:00:00Z",
            "contents": "<p>Analyze data.</p>",
        },
    ],
}


def _muse() -> TheMuseConnector:
    def handler(request: httpx.Request) -> httpx.Response:
        # Page 0 returns data; any later page returns empty so fetch terminates.
        if request.url.params.get("page") == "0":
            return httpx.Response(200, json=_PAGE)
        return httpx.Response(200, json={"page_count": 1, "results": []})

    return TheMuseConnector(max_pages=3, transport=httpx.MockTransport(handler))


def test_muse_parses_and_strips_html() -> None:
    posts = {p.external_id: p for p in _muse().fetch()}
    assert set(posts) == {"1", "2"}
    assert posts["1"].title == "Backend Engineer"
    assert posts["1"].company == "Acme"
    assert posts["1"].location == "London, United Kingdom"
    assert "Build services." in posts["1"].description and "<p>" not in posts["1"].description


def test_search_applies_uk_location_filter_and_dedup() -> None:
    outcome = search([_muse()], SearchFilters(location="United Kingdom"))
    # Only the London job survives the UK filter; Berlin is dropped.
    assert outcome.total == 1
    assert outcome.postings[0].external_id == "1"
    assert outcome.sources[0].fetched == 2
    assert outcome.sources[0].kept == 1


def test_search_keyword_filter() -> None:
    outcome = search([_muse()], SearchFilters(keyword="backend"))
    assert [p.external_id for p in outcome.postings] == ["1"]
