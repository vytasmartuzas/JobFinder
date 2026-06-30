"""Offline tests for the Adzuna connector and its key-gating."""

from __future__ import annotations

import httpx
import pytest

from jobfinder.connectors import AdzunaConnector
from jobfinder.pipeline import SearchFilters, search

_PAGE1 = {
    "results": [
        {
            "id": 555,
            "title": "Senior <strong>Engineer</strong>",
            "company": {"display_name": "Monzo"},
            "location": {"display_name": "London, UK"},
            "redirect_url": "https://adzuna/555",
            "created": "2025-03-01T08:00:00Z",
            "description": "Work on payments. Remote friendly.",
        }
    ]
}


def _adzuna(expect_where: str | None = None) -> AdzunaConnector:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("app_id") == "id"
        assert request.url.params.get("where") == expect_where
        if request.url.path.endswith("/search/1"):
            return httpx.Response(200, json=_PAGE1)
        return httpx.Response(200, json={"results": []})

    return AdzunaConnector(
        "id", "key", max_pages=2, transport=httpx.MockTransport(handler)
    )


def test_country_name_is_not_sent_as_where() -> None:
    # "United Kingdom" must NOT become ?where= (the /gb/ path already scopes to UK).
    posts = list(_adzuna(expect_where=None).fetch(location="United Kingdom"))
    assert len(posts) == 1


def test_city_is_sent_as_where() -> None:
    posts = list(_adzuna(expect_where="London").fetch(location="London"))
    assert len(posts) == 1


def test_unconfigured_adzuna_raises() -> None:
    conn = AdzunaConnector(None, None)
    assert conn.is_configured is False
    with pytest.raises(RuntimeError, match="not configured"):
        list(conn.fetch())


def test_adzuna_parses_and_cleans_title() -> None:
    posts = list(_adzuna().fetch(location="United Kingdom"))
    assert len(posts) == 1
    p = posts[0]
    assert p.title == "Senior Engineer"  # <strong> stripped
    assert p.company == "Monzo"
    assert p.location == "London, UK"
    assert p.remote is False  # remote is detected from title/location, not description


def test_uk_search_keeps_results_with_unknown_town_strings() -> None:
    # A real UK job in a town not in the alias list must survive a "United Kingdom"
    # search, because Adzuna's /gb/ endpoint already guarantees the country.
    page = {
        "results": [
            {
                "id": 9,
                "title": "Engineer",
                "company": {"display_name": "X"},
                "location": {"display_name": "Reading, Berkshire"},
                "redirect_url": "https://adzuna/9",
                "created": "2025-03-01T08:00:00Z",
                "description": "desc",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search/1"):
            return httpx.Response(200, json=page)
        return httpx.Response(200, json={"results": []})

    conn = AdzunaConnector("id", "key", max_pages=1, transport=httpx.MockTransport(handler))
    outcome = search([conn], SearchFilters(keyword="engineer", location="United Kingdom"))
    assert outcome.total == 1  # not dropped despite "Reading, Berkshire" not in aliases


def test_unconfigured_source_error_is_isolated_in_search() -> None:
    # A misconfigured source should surface as an error, not crash the search.
    outcome = search([AdzunaConnector(None, None)], SearchFilters())
    assert outcome.total == 0
    assert outcome.sources[0].error is not None
    assert "not configured" in outcome.sources[0].error
