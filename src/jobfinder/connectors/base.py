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
