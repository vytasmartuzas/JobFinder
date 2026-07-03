"""Tests for the applications service (review-queue persistence + lifecycle)."""

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


def _posting(ext_id: str = "1", title: str = "Backend Engineer") -> RawPosting:
    return RawPosting(
        source="greenhouse",
        external_id=ext_id,
        title=title,
        company="Acme",
        description="Python APIs.",
        url=f"https://jobs/{ext_id}",
        location="London, UK",
    )


def test_save_creates_job_user_and_application(db) -> None:
    from jobfinder.models import Application, ApplicationStatus, Job, User
    from jobfinder.pipeline import save_application

    with db.session_scope() as s:
        app = save_application(
            s, _posting(), tailored_content_json='{"fake": true}', match_score=42.0
        )
        assert app.status == ApplicationStatus.in_review
        assert app.match_score == 42.0

    with db.session_scope() as s:
        assert s.query(User).count() == 1
        assert s.query(Job).count() == 1
        assert s.query(Application).count() == 1


def test_saving_same_job_twice_updates_not_duplicates(db) -> None:
    from jobfinder.models import Application
    from jobfinder.pipeline import save_application

    with db.session_scope() as s:
        save_application(s, _posting(), tailored_content_json="v1")
    with db.session_scope() as s:
        app = save_application(s, _posting(), tailored_content_json="v2")
        assert app.tailored_content_json == "v2"
    with db.session_scope() as s:
        assert s.query(Application).count() == 1


def test_lifecycle_transitions(db) -> None:
    from jobfinder.models import ApplicationStatus
    from jobfinder.pipeline import save_application, set_status

    with db.session_scope() as s:
        app_id = save_application(s, _posting(), tailored_content_json="{}").id

    with db.session_scope() as s:
        set_status(s, app_id, ApplicationStatus.approved)
    with db.session_scope() as s:
        app = set_status(s, app_id, ApplicationStatus.submitted)
        assert app.submitted_at is not None
    with db.session_scope() as s:
        app = set_status(s, app_id, ApplicationStatus.responded, response_status="interview")
        assert app.response_status == "interview"


def test_invalid_transition_is_rejected(db) -> None:
    from jobfinder.models import ApplicationStatus
    from jobfinder.pipeline import save_application, set_status

    with db.session_scope() as s:
        app_id = save_application(s, _posting(), tailored_content_json="{}").id

    with db.session_scope() as s:
        with pytest.raises(ValueError, match="cannot move"):
            set_status(s, app_id, ApplicationStatus.submitted)  # skips approval


def test_list_applications_returns_detached_views(db) -> None:
    from jobfinder.models import ApplicationStatus
    from jobfinder.pipeline import list_applications, save_application

    with db.session_scope() as s:
        save_application(s, _posting("1", "Backend Engineer"), tailored_content_json="{}")
        save_application(s, _posting("2", "Data Engineer"))  # no tailoring yet

    with db.session_scope() as s:
        views = list_applications(s)

    # Usable after the session closed; both rows present with job fields joined.
    assert {v.title for v in views} == {"Backend Engineer", "Data Engineer"}
    by_title = {v.title: v for v in views}
    assert by_title["Backend Engineer"].status == ApplicationStatus.in_review
    assert by_title["Data Engineer"].status == ApplicationStatus.matched
    assert by_title["Backend Engineer"].company == "Acme"


def test_update_tailored_content(db) -> None:
    from jobfinder.pipeline import list_applications, save_application, update_tailored_content

    with db.session_scope() as s:
        app_id = save_application(s, _posting(), tailored_content_json="old").id
    with db.session_scope() as s:
        update_tailored_content(s, app_id, "new")
    with db.session_scope() as s:
        assert list_applications(s)[0].tailored_content_json == "new"
