"""CV model and rendering.

A CV is split into a fixed *template* (the layout, in ``render.py``) and *structured
content* (the data, modeled in ``content.py``). Per-application tailoring later rewrites
only the content within a validated schema, so the rendered layout never changes.
"""

from .content import (
    CVContent,
    CertEntry,
    EducationEntry,
    ExperienceEntry,
    SkillRow,
)
from .diff import FieldChange, diff_cv
from .render import render_cv_bytes, render_cv_pdf
from .tailor import TailorResult, tailor_cv

__all__ = [
    "CVContent",
    "CertEntry",
    "EducationEntry",
    "ExperienceEntry",
    "SkillRow",
    "render_cv_pdf",
    "render_cv_bytes",
    "diff_cv",
    "FieldChange",
    "tailor_cv",
    "TailorResult",
]
