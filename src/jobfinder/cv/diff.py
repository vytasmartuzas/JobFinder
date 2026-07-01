"""Diff a tailored CV against the master, for the review UI.

Only the fields tailoring is allowed to change (summary, bullet wording,
skill ordering) can differ — see ``tailor.enforce_invariants``. This produces a
flat, human-readable list of those changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .content import CVContent


@dataclass
class FieldChange:
    path: str  # human-readable location, e.g. "UAB Starflix · bullet 2"
    before: str
    after: str


def _bullet_changes(label: str, before: list[str], after: list[str]) -> list[FieldChange]:
    changes: list[FieldChange] = []
    for i in range(max(len(before), len(after))):
        b = before[i] if i < len(before) else ""
        a = after[i] if i < len(after) else ""
        if b != a:
            changes.append(FieldChange(f"{label} · point {i + 1}", b, a))
    return changes


def diff_cv(master: CVContent, tailored: CVContent) -> list[FieldChange]:
    """Return the list of text changes between master and tailored CVs."""
    changes: list[FieldChange] = []

    if master.summary != tailored.summary:
        changes.append(FieldChange("Summary", master.summary, tailored.summary))

    for m, t in zip(master.education, tailored.education):
        changes += _bullet_changes(f"{m.institution} · project", m.projects, t.projects)

    for m, t in zip(master.certifications, tailored.certifications):
        changes += _bullet_changes(m.title, m.bullets, t.bullets)

    for m, t in zip(master.experience, tailored.experience):
        changes += _bullet_changes(m.organization, m.bullets, t.bullets)

    m_order = [s.category for s in master.skills]
    t_order = [s.category for s in tailored.skills]
    if m_order != t_order:
        changes.append(FieldChange("Skills order", ", ".join(m_order), ", ".join(t_order)))

    return changes
