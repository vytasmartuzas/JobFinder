"""Job-source connectors.

Each connector wraps one legal source (a public ATS API or feed) and implements the
``Connector`` interface. Adding a source is writing one class — the ingest pipeline
never changes.
"""

from .base import Connector

__all__ = ["Connector"]
