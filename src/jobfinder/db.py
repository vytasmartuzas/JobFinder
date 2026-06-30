"""Database engine and session management.

v1 uses SQLite. Because everything goes through SQLAlchemy and a single
``database_url``, moving to Postgres in v2 is a config change, not a code change.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

# check_same_thread=False lets Streamlit's threads share the SQLite connection pool.
_connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables for any models imported before this is called."""
    from . import models  # noqa: F401  (import registers models on the metadata)

    settings.ensure_dirs()
    models.Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session scope: commit on success, roll back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
