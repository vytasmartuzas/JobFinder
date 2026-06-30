"""Canonical data shapes passed between pipeline stages.

These are plain Pydantic models (not ORM rows). Connectors emit ``RawPosting``;
the ingester maps those into the ``Job`` ORM row. Keeping this contract separate
from the database lets connectors be tested without a DB.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from pydantic import BaseModel


class RawPosting(BaseModel):
    """A normalized posting emitted by a connector, before it is persisted."""

    source: str
    external_id: str
    title: str
    company: str
    description: str
    url: str
    location: str | None = None
    remote: bool = False
    posted_at: datetime | None = None

    def content_hash(self) -> str:
        """Stable hash of identifying content, for cross-source de-duplication.

        Two postings of the same role (same company/title/location) on different
        sources collapse to one hash, so we don't review the same job twice.
        """
        basis = f"{self.company.strip().lower()}|{self.title.strip().lower()}|{(self.location or '').strip().lower()}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()
