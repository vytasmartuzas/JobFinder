"""Greenhouse job-board connector.

Greenhouse exposes a public, keyless API per company "board token":

    https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

`content=true` includes each job's description. The board API has no server-side
search, so `query` and `since` are applied client-side here.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

import httpx

from ..schema import RawPosting
from ..textutil import html_to_text
from .base import Connector

_BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Normalize to timezone-aware UTC for consistent comparisons.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class GreenhouseConnector(Connector):
    """Fetches postings from one or more Greenhouse company boards."""

    name = "greenhouse"

    def __init__(
        self,
        board_tokens: Iterable[str],
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.board_tokens = [t.strip() for t in board_tokens if t and t.strip()]
        self.timeout = timeout
        # Injectable for offline tests; None means a real network transport.
        self.transport = transport

    def fetch(self, query: str = "", since: datetime | None = None) -> Iterable[RawPosting]:
        query_l = query.strip().lower()
        with httpx.Client(
            timeout=self.timeout, follow_redirects=True, transport=self.transport
        ) as client:
            for board in self.board_tokens:
                yield from self._fetch_board(client, board, query_l, since)

    def _fetch_board(
        self,
        client: httpx.Client,
        board: str,
        query_l: str,
        since: datetime | None,
    ) -> Iterable[RawPosting]:
        resp = client.get(_BASE_URL.format(board=board), params={"content": "true"})
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])

        for job in jobs:
            posted_at = _parse_dt(job.get("first_published") or job.get("updated_at"))
            if since is not None and posted_at is not None and posted_at < since:
                continue

            title = job.get("title", "") or ""
            description = html_to_text(job.get("content"))

            if query_l and query_l not in f"{title}\n{description}".lower():
                continue

            location = (job.get("location") or {}).get("name")
            yield RawPosting(
                source=self.name,
                external_id=str(job["id"]),
                title=title,
                # The board API doesn't name the company; the board token stands in.
                company=board,
                description=description,
                url=job.get("absolute_url", ""),
                location=location,
                remote=bool(location and "remote" in location.lower()),
                posted_at=posted_at,
            )
