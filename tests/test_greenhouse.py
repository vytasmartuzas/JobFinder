"""Offline tests for the Greenhouse connector, using a mocked HTTP transport."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from jobfinder.connectors import GreenhouseConnector

_PAYLOAD = {
    "jobs": [
        {
            "id": 101,
            "title": "Senior Backend Engineer",
            "absolute_url": "https://example.com/101",
            "updated_at": "2025-01-10T12:00:00-05:00",
            "first_published": "2025-01-05T09:00:00-05:00",
            "location": {"name": "Remote - US"},
            "content": "Build &lt;b&gt;APIs&lt;/b&gt;.&lt;br&gt;You&amp;#39;ll ship code.",
        },
        {
            "id": 102,
            "title": "Office Manager",
            "absolute_url": "https://example.com/102",
            "updated_at": "2024-06-01T12:00:00-04:00",
            "first_published": "2024-06-01T12:00:00-04:00",
            "location": {"name": "Berlin, Germany"},
            "content": "Run the office.",
        },
    ]
}


def _connector(board: str = "acme") -> GreenhouseConnector:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("content") == "true"
        return httpx.Response(200, json=_PAYLOAD)

    return GreenhouseConnector([board], transport=httpx.MockTransport(handler))


def test_fetch_normalizes_fields() -> None:
    posts = {p.external_id: p for p in _connector().fetch()}
    assert set(posts) == {"101", "102"}

    eng = posts["101"]
    assert eng.title == "Senior Backend Engineer"
    assert eng.company == "acme"
    assert eng.remote is True  # location contains "remote"
    assert eng.url == "https://example.com/101"
    # HTML stripped to readable text, entities decoded (incl. double-encoded &#39;).
    assert "APIs" in eng.description and "<b>" not in eng.description
    assert "You'll ship code." in eng.description
    # first_published preferred over updated_at.
    assert eng.posted_at == datetime(2025, 1, 5, 9, 0, tzinfo=timezone(_offset(-5)))


def test_query_filters_by_title_or_description() -> None:
    posts = list(_connector().fetch(query="backend"))
    assert [p.external_id for p in posts] == ["101"]


def test_since_filters_older_postings() -> None:
    cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)
    posts = list(_connector().fetch(since=cutoff))
    assert [p.external_id for p in posts] == ["101"]  # 102 was published in 2024


def _offset(hours: int):
    from datetime import timedelta

    return timedelta(hours=hours)


def test_payload_is_valid_json() -> None:
    # Guard against accidental edits breaking the fixture.
    json.dumps(_PAYLOAD)
