"""Ingest & normalize stage.

Takes ``RawPosting`` objects from a connector and persists them as canonical ``Job``
rows, de-duplicating two ways:

  - ``(source, external_id)`` — the same posting re-fetched from the same source.
  - ``content_hash`` — the same role cross-posted on a different source.

Each run is recorded as a ``SourceRun`` for bookkeeping / incremental pulls.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..connectors.base import Connector
from ..models import Job, SourceRun
from ..schema import RawPosting


@dataclass
class IngestStats:
    found: int = 0
    new: int = 0
    duplicates: int = 0  # already present (same source) or cross-source dupes


def ingest_postings(
    session: Session, postings: Iterable[RawPosting], *, source: str
) -> IngestStats:
    """Persist postings into ``Job``, skipping ones already known. Caller commits."""
    stats = IngestStats()

    # Cache hashes/ids seen during this batch so duplicates within one fetch collapse.
    seen_hashes: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()

    for posting in postings:
        stats.found += 1
        key = (posting.source, posting.external_id)
        content_hash = posting.content_hash()

        if key in seen_keys or content_hash in seen_hashes:
            stats.duplicates += 1
            continue

        existing = session.scalar(
            select(Job.id).where(
                (Job.source == posting.source) & (Job.external_id == posting.external_id)
            )
        )
        if existing is None:
            existing = session.scalar(select(Job.id).where(Job.content_hash == content_hash))

        if existing is not None:
            stats.duplicates += 1
        else:
            session.add(
                Job(
                    source=posting.source,
                    external_id=posting.external_id,
                    title=posting.title,
                    company=posting.company,
                    location=posting.location,
                    remote=posting.remote,
                    description=posting.description,
                    url=posting.url,
                    posted_at=posting.posted_at,
                    content_hash=content_hash,
                )
            )
            stats.new += 1

        seen_keys.add(key)
        seen_hashes.add(content_hash)

    _ = source  # reserved for future per-source routing; kept for call-site clarity
    return stats


def run_connector(
    session: Session, connector: Connector, *, query: str = "", since: datetime | None = None
) -> IngestStats:
    """Run a connector end-to-end: fetch -> ingest -> record a SourceRun."""
    run = SourceRun(source=connector.name, started_at=datetime.now(timezone.utc))
    session.add(run)
    try:
        stats = ingest_postings(session, connector.fetch(query, since), source=connector.name)
    except Exception as exc:  # record the failure on the run before re-raising
        run.error = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        raise
    run.jobs_found = stats.found
    run.jobs_new = stats.new
    run.finished_at = datetime.now(timezone.utc)
    return stats
