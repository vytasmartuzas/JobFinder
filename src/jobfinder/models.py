"""SQLAlchemy ORM models — the persistent data model from ARCHITECTURE.md.

Everything is scoped to a ``User`` from day one so the v1 single-user build grows
into the v2 multi-user app without a schema redesign.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ApplicationStatus(str, enum.Enum):
    """Lifecycle of a single application (see ARCHITECTURE.md)."""

    discovered = "discovered"
    matched = "matched"
    tailored = "tailored"
    in_review = "in_review"
    approved = "approved"
    submitted = "submitted"
    responded = "responded"
    rejected = "rejected"


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    cv_documents: Mapped[list[CvDocument]] = relationship(back_populates="user")
    applications: Mapped[list[Application]] = relationship(back_populates="user")


class CvDocument(Base):
    """A CV as fixed template + structured content (never an edited PDF blob)."""

    __tablename__ = "cv_document"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    name: Mapped[str] = mapped_column(String(200))
    template_ref: Mapped[str] = mapped_column(String(200))  # which template renders this
    content_json: Mapped[str] = mapped_column(Text)  # structured CV content (the data)
    is_master: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="cv_documents")


class Job(Base):
    """A canonical, normalized job posting from any connector."""

    __tablename__ = "job"
    __table_args__ = (
        # Same posting from the same source is ingested once.
        UniqueConstraint("source", "external_id", name="uq_job_source_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(400))
    company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    remote: Mapped[bool] = mapped_column(default=False)
    description: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1000))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)  # cross-source dedupe

    applications: Mapped[list[Application]] = relationship(back_populates="job")


class Application(Base):
    """One user's application to one job, with its tailored artifacts and status."""

    __tablename__ = "application"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_application_user_job"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id"))
    cv_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_document.id"), nullable=True
    )

    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus), default=ApplicationStatus.discovered
    )
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    tailored_content_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_letter_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_cv_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="applications")
    job: Mapped[Job] = relationship(back_populates="applications")


class SourceRun(Base):
    """Bookkeeping for each connector fetch, to support incremental (`since`) pulls."""

    __tablename__ = "source_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jobs_found: Mapped[int] = mapped_column(default=0)
    jobs_new: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
