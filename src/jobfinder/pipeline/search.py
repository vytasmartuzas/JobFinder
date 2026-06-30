"""Search orchestrator.

Runs a set of connectors for one query and returns a fresh, de-duplicated result
list — the "each search starts from zero" behaviour. Results are ephemeral (not
persisted); the DB-backed ingest stage is used later when a job becomes an
application. The location filter here is authoritative, so UK searches behave
consistently even when a source can't filter by location server-side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config import Settings, settings as default_settings
from ..connectors import AdzunaConnector, Connector, GreenhouseConnector, TheMuseConnector
from ..locations import expand_location_query, location_matches
from ..schema import RawPosting

# Default UK boards for Greenhouse (per-company source); editable in the UI.
# Greenhouse is per-company, and most UK firms use other ATSes, so this is a small
# bonus set — the aggregators (The Muse, Adzuna) carry UK breadth.
DEFAULT_GREENHOUSE_BOARDS = ["monzo", "gocardless", "wayve"]

# The Muse only filters by "City, Country"; this preset broadens a UK search.
UK_MUSE_LOCATIONS = [
    "London, United Kingdom",
    "Manchester, United Kingdom",
    "Edinburgh, United Kingdom",
    "Birmingham, United Kingdom",
    "Cambridge, United Kingdom",
]

ALL_SOURCES = ("greenhouse", "themuse", "adzuna")

_UTC_MIN = datetime.min.replace(tzinfo=timezone.utc)


@dataclass
class SearchFilters:
    keyword: str = ""
    location: str = ""
    since: datetime | None = None


@dataclass
class SourceResult:
    source: str
    fetched: int = 0
    kept: int = 0
    error: str | None = None


@dataclass
class SearchOutcome:
    postings: list[RawPosting] = field(default_factory=list)
    sources: list[SourceResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.postings)


def _is_uk_query(location: str) -> bool:
    return "united kingdom" in expand_location_query(location)


def muse_locations_for(location: str) -> list[str]:
    """Pick The Muse server-side locations for a location query."""
    if not location.strip():
        return []
    if _is_uk_query(location):
        return UK_MUSE_LOCATIONS
    return [location.strip()]


def build_connectors(
    sources: list[str],
    *,
    location: str = "",
    greenhouse_boards: list[str] | None = None,
    settings: Settings | None = None,
) -> list[Connector]:
    """Construct the selected connectors, wiring in settings/secrets."""
    settings = settings or default_settings
    boards = greenhouse_boards if greenhouse_boards is not None else DEFAULT_GREENHOUSE_BOARDS

    connectors: list[Connector] = []
    if "greenhouse" in sources:
        connectors.append(GreenhouseConnector(boards))
    if "themuse" in sources:
        connectors.append(TheMuseConnector(locations=muse_locations_for(location)))
    if "adzuna" in sources:
        connectors.append(
            AdzunaConnector(settings.adzuna_app_id, settings.adzuna_app_key)
        )
    return connectors


def search(connectors: list[Connector], filters: SearchFilters) -> SearchOutcome:
    """Fetch from all connectors, filter by location, dedupe, sort newest-first."""
    outcome = SearchOutcome()
    seen_hashes: set[str] = set()

    for connector in connectors:
        result = SourceResult(source=connector.name)
        try:
            for posting in connector.fetch(
                query=filters.keyword, since=filters.since, location=filters.location
            ):
                result.fetched += 1
                if not location_matches(posting.location, filters.location):
                    continue
                content_hash = posting.content_hash()
                if content_hash in seen_hashes:
                    continue
                seen_hashes.add(content_hash)
                outcome.postings.append(posting)
                result.kept += 1
        except Exception as exc:  # one bad source shouldn't sink the whole search
            result.error = str(exc)
        outcome.sources.append(result)

    outcome.postings.sort(key=lambda p: p.posted_at or _UTC_MIN, reverse=True)
    return outcome
