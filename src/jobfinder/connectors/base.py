"""The connector interface every job source implements.

A connector's only job is: given a query (and optionally a `since` cutoff for
incremental pulls), yield normalized ``RawPosting`` objects. It does no database
work and no filtering — that belongs to later pipeline stages.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime

from ..schema import RawPosting


class Connector(ABC):
    """Base class for all job-source connectors."""

    #: Short, stable identifier stored on each Job (e.g. "greenhouse", "lever").
    name: str

    def guarantees_location(self, location: str) -> bool:
        """True if this source's results are already constrained to `location`.

        When True, the search orchestrator skips its client-side location filter for
        this connector — avoiding dropping valid results whose free-text location
        strings (counties, towns) aren't in the matcher's alias list. Sources that
        return mixed locations should leave this False (the default).
        """
        return False

    @abstractmethod
    def fetch(
        self, query: str = "", since: datetime | None = None, location: str = ""
    ) -> Iterable[RawPosting]:
        """Yield normalized postings for the given filters.

        `query` is a keyword, `since` a recency cutoff, `location` a place hint.
        Connectors apply whichever filters their source supports server-side; the
        search orchestrator re-applies keyword/location uniformly so behavior is
        consistent even when a source ignores a filter.
        """
        raise NotImplementedError
