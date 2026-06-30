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


def _adzuna() -> AdzunaConnector:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("app_id") == "id"
        assert request.url.params.get("where") == "United Kingdom"
        if request.url.path.endswith("/search/1"):
            return httpx.Response(200, json=_PAGE1)
        return httpx.Response(200, json={"results": []})

    return AdzunaConnector(
        "id", "key", max_pages=2, transport=httpx.MockTransport(handler)
    )


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


def test_unconfigured_source_error_is_isolated_in_search() -> None:
    # A misconfigured source should surface as an error, not crash the search.
    outcome = search([AdzunaConnector(None, None)], SearchFilters())
    assert outcome.total == 0
    assert outcome.sources[0].error is not None
    assert "not configured" in outcome.sources[0].error
