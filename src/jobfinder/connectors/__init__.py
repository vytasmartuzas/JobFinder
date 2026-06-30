"""Job-source connectors.

Each connector wraps one legal source (a public ATS API or feed) and implements the
``Connector`` interface. Adding a source is writing one class — the search/ingest
pipeline never changes.
"""

from .adzuna import AdzunaConnector
from .base import Connector
from .greenhouse import GreenhouseConnector
from .themuse import TheMuseConnector

__all__ = ["Connector", "GreenhouseConnector", "TheMuseConnector", "AdzunaConnector"]
