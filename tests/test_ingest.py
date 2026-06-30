"""Tests for the ingest stage: persistence and two-way de-duplication."""

from __future__ import annotations

import importlib

import pytest

from jobfinder.schema import RawPosting


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A fresh SQLite database bound to a temp file for each test."""
    monkeypatch.setenv("JOBFINDER_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    from jobfinder import config, db as db_module

    importlib.reload(config)
    importlib.reload(db_module)
    db_module.init_db()
    return db_module


def _posting(source: str, ext_id: str, *, title: str = "Engineer", company: str = "Acme",
             location: str = "Remote") -> RawPosting:
    return RawPosting(
        source=source,
        external_id=ext_id,
        title=title,
        company=company,
        description="desc",
        url=f"https://x/{ext_id}",
        location=location,
    )


def test_new_postings_are_inserted(db) -> None:
    from jobfinder.models import Job
    from jobfinder.pipeline import ingest_postings

    with db.session_scope() as s:
        stats = ingest_postings(s, [_posting("greenhouse", "1"), _posting("greenhouse", "2",
                                  title="Designer")], source="greenhouse")
    assert (stats.found, stats.new, stats.duplicates) == (2, 2, 0)
    with db.session_scope() as s:
        assert s.query(Job).count() == 2


def test_same_source_id_is_deduped(db) -> None:
    from jobfinder.pipeline import ingest_postings

    with db.session_scope() as s:
        ingest_postings(s, [_posting("greenhouse", "1")], source="greenhouse")
    with db.session_scope() as s:
        stats = ingest_postings(s, [_posting("greenhouse", "1")], source="greenhouse")
    assert (stats.new, stats.duplicates) == (0, 1)


def test_cross_source_same_role_is_deduped(db) -> None:
    from jobfinder.models import Job
    from jobfinder.pipeline import ingest_postings

    # Same company/title/location on two different sources -> one Job.
    with db.session_scope() as s:
        ingest_postings(s, [_posting("greenhouse", "1")], source="greenhouse")
    with db.session_scope() as s:
        stats = ingest_postings(s, [_posting("lever", "zzz")], source="lever")
    assert (stats.new, stats.duplicates) == (0, 1)
    with db.session_scope() as s:
        assert s.query(Job).count() == 1
