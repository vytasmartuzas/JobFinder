"""Tests for the CV content model and the fixed-template renderer."""

from __future__ import annotations

from pathlib import Path

from jobfinder.cv import CVContent, render_cv_pdf
from jobfinder.cv.render import _safe

REPO_ROOT = Path(__file__).resolve().parents[1]
# Tests use the committed, anonymized example so they pass on any clone.
EXAMPLE = REPO_ROOT / "cv" / "example_cv.json"


def test_example_cv_loads_and_validates() -> None:
    cv = CVContent.load(EXAMPLE)
    assert cv.name and cv.contact_lines
    assert cv.education and cv.education[0].modules
    assert cv.skills and cv.experience


def test_content_json_roundtrip() -> None:
    cv = CVContent.load(EXAMPLE)
    again = CVContent.from_json(cv.to_json())
    assert again == cv


def test_render_produces_pdf(tmp_path) -> None:
    out = render_cv_pdf(CVContent.load(EXAMPLE), tmp_path / "cv.pdf")
    assert out.exists()
    head = out.read_bytes()[:5]
    assert head == b"%PDF-"
    assert out.stat().st_size > 2000  # non-trivial document


def test_render_tolerates_unencodable_characters(tmp_path) -> None:
    # Tailoring could introduce characters outside the core-font encoding; the
    # renderer must substitute rather than crash.
    cv = CVContent.load(EXAMPLE)
    cv.summary = "Smart “quotes”, em — dash, snowman ☃ and emoji \U0001f600."
    out = render_cv_pdf(cv, tmp_path / "cv.pdf")
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"


def test_safe_replaces_out_of_charset() -> None:
    assert _safe("plain") == "plain"
    assert "?" in _safe("snowman ☃")  # not representable -> replaced
