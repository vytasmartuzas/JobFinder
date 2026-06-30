"""Adzuna connector — UK-focused aggregator with server-side keyword + location.

API (free key required): https://developer.adzuna.com

    GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
        ?app_id=...&app_key=...&what=engineer&where=london&results_per_page=50

`country="gb"` targets the UK. Both keyword (`what`) and location (`where`) are applied
server-side, which makes Adzuna the strongest source for UK searches.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

import httpx

from ..schema import RawPosting
from ..textutil import html_to_text
from .base import Connector

_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class AdzunaConnector(Connector):
    """Fetches postings from Adzuna for a given country (default UK)."""

    name = "adzuna"

    def __init__(
        self,
        app_id: str | None,
        app_key: str | None,
        country: str = "gb",
        max_pages: int = 2,
        results_per_page: int = 50,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.country = country
        self.max_pages = max_pages
        self.results_per_page = results_per_page
        self.timeout = timeout
        self.transport = transport

    @property
    def is_configured(self) -> bool:
        """Adzuna needs a free app_id + app_key; skip the source if missing."""
        return bool(self.app_id and self.app_key)

    def fetch(
        self, query: str = "", since: datetime | None = None, location: str = ""
    ) -> Iterable[RawPosting]:
        if not self.is_configured:
            raise RuntimeError(
                "Adzuna is not configured. Set ADZUNA_APP_ID and ADZUNA_APP_KEY "
                "(free key from https://developer.adzuna.com) to enable this source."
            )

        base_params: dict[str, str] = {
            "app_id": self.app_id or "",
            "app_key": self.app_key or "",
            "results_per_page": str(self.results_per_page),
        }
        if query.strip():
            base_params["what"] = query.strip()
        if location.strip():
            base_params["where"] = location.strip()
        if since is not None:
            days = max(1, (datetime.now(timezone.utc) - since).days)
            base_params["max_days_old"] = str(days)

        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            for page in range(1, self.max_pages + 1):  # Adzuna pages are 1-indexed
                resp = client.get(
                    _URL.format(country=self.country, page=page), params=base_params
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
                if not results:
                    break
                for job in results:
                    posting = self._to_posting(job)
                    if posting is not None:
                        yield posting

    def _to_posting(self, job: dict) -> RawPosting | None:
        job_id = job.get("id")
        if job_id is None:
            return None
        location = (job.get("location") or {}).get("display_name")
        title = job.get("title", "") or ""
        return RawPosting(
            source=self.name,
            external_id=str(job_id),
            title=html_to_text(title),  # Adzuna wraps matched terms in <strong>
            company=(job.get("company") or {}).get("display_name", "") or "",
            description=html_to_text(job.get("description")),
            url=job.get("redirect_url", "") or "",
            location=location,
            remote=bool(location and "remote" in location.lower())
            or "remote" in title.lower(),
            posted_at=_parse_dt(job.get("created")),
        )
