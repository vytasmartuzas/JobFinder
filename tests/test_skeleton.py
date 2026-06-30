"""Smoke tests for the v1 skeleton: schema hashing and DB init/insert."""

from __future__ import annotations

from jobfinder.schema import RawPosting


def test_content_hash_is_source_independent() -> None:
    """The same role from two sources hashes identically (so it dedupes)."""
    a = RawPosting(
        source="greenhouse",
        external_id="1",
        title="Backend Engineer",
        company="Acme",
        description="...",
        url="https://a",
        location="Remote",
    )
    b = RawPosting(
        source="lever",
        external_id="zzz",
        title="  backend engineer ",
        company="ACME",
        description="different text",
        url="https://b",
        location="remote",
    )
    assert a.content_hash() == b.content_hash()


def test_db_init_and_insert(tmp_path, monkeypatch) -> None:
    """init_db creates tables and a User round-trips."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("JOBFINDER_DATABASE_URL", f"sqlite:///{db_file}")

    # Re-import with the patched env so the engine binds to the temp database.
    import importlib

    from jobfinder import config, db

    importlib.reload(config)
    importlib.reload(db)

    db.init_db()
    from jobfinder.models import User

    with db.session_scope() as session:
        session.add(User(name="Test", email="t@example.com"))

    with db.session_scope() as session:
        assert session.query(User).count() == 1
