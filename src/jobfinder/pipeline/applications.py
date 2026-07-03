"""Applications service — the review queue's persistence layer.

Turns an ephemeral search result (RawPosting) plus a tailored CV into a durable
``Application`` row tied to a ``Job``, and moves it through the lifecycle:

    in_review -> approved -> submitted -> responded   (or rejected at any point)

The UI reads ``ApplicationView`` snapshots (plain data, safe to use after the DB
session closes) and mutates state only through the functions here, so a future
FastAPI backend can reuse the same service unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Application, ApplicationStatus, Job, User
from ..schema import RawPosting
from .ingest import ingest_postings

DEFAULT_USER = ("Local User", "local@jobfinder")


def get_or_create_default_user(session: Session) -> User:
    """v1 is single-user: one seeded row, created on first use."""
    user = session.scalar(select(User).where(User.email == DEFAULT_USER[1]))
    if user is None:
        user = User(name=DEFAULT_USER[0], email=DEFAULT_USER[1])
        session.add(user)
        session.flush()
    return user


def _find_job(session: Session, posting: RawPosting) -> Job | None:
    job = session.scalar(
        select(Job).where(
            (Job.source == posting.source) & (Job.external_id == posting.external_id)
        )
    )
    if job is None:
        job = session.scalar(select(Job).where(Job.content_hash == posting.content_hash()))
    return job


def save_application(
    session: Session,
    posting: RawPosting,
    *,
    tailored_content_json: str | None = None,
    match_score: float | None = None,
) -> Application:
    """Persist the posting as a Job (deduped) and create/update its Application.

    Saving the same job again updates the existing application (fresh tailoring
    replaces the old one) rather than creating a duplicate.
    """
    user = get_or_create_default_user(session)
    ingest_postings(session, [posting], source=posting.source)
    session.flush()
    job = _find_job(session, posting)
    assert job is not None  # ingest just persisted (or matched) it

    app = session.scalar(
        select(Application).where(
            (Application.user_id == user.id) & (Application.job_id == job.id)
        )
    )
    if app is None:
        app = Application(user_id=user.id, job_id=job.id)
        session.add(app)

    if match_score is not None:
        app.match_score = match_score
    if tailored_content_json is not None:
        app.tailored_content_json = tailored_content_json
        app.status = ApplicationStatus.in_review
    elif app.status in (None, ApplicationStatus.discovered):
        # None: a brand-new row — the column default only applies at flush time.
        app.status = ApplicationStatus.matched
    session.flush()
    return app


# Which statuses each action is allowed from — the UI derives its buttons from this.
ALLOWED_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.approved: {ApplicationStatus.in_review},
    ApplicationStatus.submitted: {ApplicationStatus.approved},
    ApplicationStatus.responded: {ApplicationStatus.submitted},
    ApplicationStatus.rejected: {
        ApplicationStatus.discovered,
        ApplicationStatus.matched,
        ApplicationStatus.tailored,
        ApplicationStatus.in_review,
        ApplicationStatus.approved,
    },
}


def set_status(
    session: Session,
    application_id: int,
    status: ApplicationStatus,
    *,
    notes: str | None = None,
    response_status: str | None = None,
) -> Application:
    app = session.get(Application, application_id)
    if app is None:
        raise ValueError(f"no application with id {application_id}")
    allowed = ALLOWED_TRANSITIONS.get(status)
    if allowed is not None and app.status not in allowed:
        raise ValueError(f"cannot move {app.status.value} -> {status.value}")
    app.status = status
    if status == ApplicationStatus.submitted and app.submitted_at is None:
        app.submitted_at = datetime.now(timezone.utc)
    if notes is not None:
        app.notes = notes
    if response_status is not None:
        app.response_status = response_status
    return app


def update_tailored_content(session: Session, application_id: int, content_json: str) -> None:
    """Store user-edited tailored content (the UI validates it first)."""
    app = session.get(Application, application_id)
    if app is None:
        raise ValueError(f"no application with id {application_id}")
    app.tailored_content_json = content_json


@dataclass
class ApplicationView:
    """A detached snapshot of an application + its job, safe outside the session."""

    id: int
    status: ApplicationStatus
    title: str
    company: str
    location: str | None
    url: str
    match_score: float | None
    tailored_content_json: str | None
    notes: str | None
    response_status: str | None
    created_at: datetime | None
    submitted_at: datetime | None


def list_applications(session: Session) -> list[ApplicationView]:
    rows = session.execute(
        select(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .order_by(Application.created_at.desc())
    ).all()
    return [
        ApplicationView(
            id=app.id,
            status=app.status,
            title=job.title,
            company=job.company,
            location=job.location,
            url=job.url,
            match_score=app.match_score,
            tailored_content_json=app.tailored_content_json,
            notes=app.notes,
            response_status=app.response_status,
            created_at=app.created_at,
            submitted_at=app.submitted_at,
        )
        for app, job in rows
    ]
