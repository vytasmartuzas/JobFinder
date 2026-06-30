"""The Muse connector — a keyless job aggregator spanning many companies.

API: https://www.themuse.com/api/public/jobs?page=N&location=City%2C%20Country

No API key is required (an optional key raises rate limits). The Muse has no
free-text keyword parameter, so `query` is applied client-side; `location` is passed
server-side (it expects "City, Country" form), and the search orchestrator re-applies
the authoritative location filter on top.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

import httpx

from ..schema import RawPosting
from ..textutil import html_to_text
from .base import Connector

_URL = "https://www.themuse.com/api/public/jobs"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class TheMuseConnector(Connector):
    """Fetches postings from The Muse, optionally narrowed to given locations."""

    name = "themuse"

    def __init__(
        self,
        api_key: str | None = None,
        locations: Iterable[str] | None = None,
        max_pages: int = 3,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.locations = [loc for loc in (locations or []) if loc.strip()]
        self.max_pages = max_pages
        self.timeout = timeout
        self.transport = transport

    def fetch(
        self, query: str = "", since: datetime | None = None, location: str = ""
    ) -> Iterable[RawPosting]:
        query_l = query.strip().lower()
        # Prefer explicit constructor locations; fall back to the single fetch arg.
        server_locations = self.locations or ([location] if location.strip() else [])

        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            for page in range(self.max_pages):
                params: list[tuple[str, str]] = [("page", str(page))]
                if self.api_key:
                    params.append(("api_key", self.api_key))
                params.extend(("location", loc) for loc in server_locations)

                resp = client.get(_URL, params=params)
                if resp.status_code == 400:
                    break  # past the last page
                resp.raise_for_status()
                body = resp.json()
                results = body.get("results", [])
                if not results:
                    break

                for job in results:
                    posting = self._to_posting(job)
                    if posting is None:
                        continue
                    if since and posting.posted_at and posting.posted_at < since:
                        continue
                    if query_l and query_l not in f"{posting.title}\n{posting.description}".lower():
                        continue
                    yield posting

                if page + 1 >= body.get("page_count", 0):
                    break

    def _to_posting(self, job: dict) -> RawPosting | None:
        job_id = job.get("id")
        if job_id is None:
            return None
        loc_names = [loc.get("name", "") for loc in job.get("locations", []) if loc.get("name")]
        location = "; ".join(loc_names)
        return RawPosting(
            source=self.name,
            external_id=str(job_id),
            title=job.get("name", "") or "",
            company=(job.get("company") or {}).get("name", "") or "",
            description=html_to_text(job.get("contents")),
            url=(job.get("refs") or {}).get("landing_page", "") or "",
            location=location or None,
            remote=any(t in location.lower() for t in ("remote", "flexible")),
            posted_at=_parse_dt(job.get("publication_date")),
        )
