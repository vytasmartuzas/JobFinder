"""Structured CV content — the *data* half of the CV (the template is the layout).

These Pydantic models define the schema the per-application tailoring step must stay
within: it may rewrite text inside these fields, but not add or remove sections, so the
rendered structure is identical to the master every time.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class EducationEntry(BaseModel):
    institution: str
    dates: str = ""
    degree: str = ""
    modules: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)


class CertEntry(BaseModel):
    title: str
    date: str = ""
    bullets: list[str] = Field(default_factory=list)


class SkillRow(BaseModel):
    category: str
    items: str


class ExperienceEntry(BaseModel):
    organization: str
    dates: str = ""
    role: str = ""
    bullets: list[str] = Field(default_factory=list)


class CVContent(BaseModel):
    """The full content of one CV."""

    name: str
    contact_lines: list[str] = Field(default_factory=list)
    summary: str = ""
    education: list[EducationEntry] = Field(default_factory=list)
    certifications: list[CertEntry] = Field(default_factory=list)
    skills: list[SkillRow] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> CVContent:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    @classmethod
    def from_json(cls, raw: str) -> CVContent:
        return cls.model_validate_json(raw)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")
