"""Pipeline stages: search/ingest -> match -> tailor -> review -> submit.

Each stage is a plain function operating on the database and canonical schema
objects, so stages can be run from the UI, a CLI, or scheduled workers alike.
"""

from .ingest import IngestStats, ingest_postings, run_connector
from .search import (
    ALL_SOURCES,
    DEFAULT_GREENHOUSE_BOARDS,
    SearchFilters,
    SearchOutcome,
    SourceResult,
    build_connectors,
    search,
)

__all__ = [
    "IngestStats",
    "ingest_postings",
    "run_connector",
    "ALL_SOURCES",
    "DEFAULT_GREENHOUSE_BOARDS",
    "SearchFilters",
    "SearchOutcome",
    "SourceResult",
    "build_connectors",
    "search",
]
