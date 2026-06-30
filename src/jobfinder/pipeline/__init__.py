"""Pipeline stages: ingest -> match -> tailor -> review -> submit.

Each stage is a plain function operating on the database and canonical schema
objects, so stages can be run from the UI, a CLI, or scheduled workers alike.
"""

from .ingest import IngestStats, ingest_postings, run_connector

__all__ = ["IngestStats", "ingest_postings", "run_connector"]
