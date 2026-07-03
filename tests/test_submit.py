"""Tests for the submission assist: profile parsing, field mapping, and a live
prefill against a local HTML form (skipped if no system browser is available)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobfinder.cv import CVContent
from jobfinder.submit import (
    BROWSER_CHANNELS,
    ApplicantProfile,
    PrefillReport,
    classify_field,
    prefill_frame,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "cv" / "example_cv.json"


def test_profile_from_cv_parses_contacts() -> None:
    p = ApplicantProfile.from_cv(CVContent.load(EXAMPLE))
    assert p.full_name == "Alex Example"
    assert (p.first_name, p.last_name) == ("Alex", "Example")
    assert p.email == "alex.example@email.com"
    assert p.phone == "00000 000000"
    assert p.linkedin == "https://linkedin.com/in/alex-example"
    assert p.github == "https://github.com/alexexample"
    assert p.location == "Anytown, UK"


@pytest.mark.parametrize(
    ("descriptor", "expected"),
    [
        ("first_name First Name", "first_name"),
        ("job_application[last_name]", "last_name"),
        ("email your e-mail address", "email"),
        ("candidate-phone-number", "phone"),
        ("input_linkedin_url LinkedIn profile", "linkedin"),
        ("location City", "location"),
        ("name Your full name", "full_name"),
        ("username", None),  # looks like a name field but isn't
        ("company_name", None),
        ("salary expectations", None),
    ],
)
def test_classify_field(descriptor: str, expected: str | None) -> None:
    assert classify_field(descriptor) == expected


_FORM = """<!doctype html><html><body><form>
  <label for="fn">First Name</label><input id="fn" type="text">
  <input name="last_name" type="text">
  <input type="email" name="email">
  <input type="tel" placeholder="Phone number">
  <input type="text" name="username">
  <label for="res">Upload your resume/CV</label><input id="res" type="file" name="resume">
</form></body></html>"""


def test_prefill_fills_a_real_form(tmp_path) -> None:
    playwright = pytest.importorskip("playwright.sync_api")

    html = tmp_path / "form.html"
    html.write_text(_FORM, encoding="utf-8")
    fake_pdf = tmp_path / "cv.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    profile = ApplicantProfile.from_cv(CVContent.load(EXAMPLE))
    report = PrefillReport()

    with playwright.sync_playwright() as pw:
        browser = None
        for channel in BROWSER_CHANNELS:
            try:
                browser = pw.chromium.launch(channel=channel, headless=True)
                break
            except Exception:
                continue
        if browser is None:
            pytest.skip("no system browser available")

        page = browser.new_page()
        page.goto(html.as_uri())
        prefill_frame(page.main_frame, profile, fake_pdf, report)

        assert page.input_value("#fn") == "Alex"
        assert page.input_value('[name="last_name"]') == "Example"
        assert page.input_value('[name="email"]') == "alex.example@email.com"
        assert page.input_value('[type="tel"]') == "00000 000000"
        assert page.input_value('[name="username"]') == ""  # blocklisted, untouched
        browser.close()

    assert report.uploaded is True
    filled_keys = {k for k, _ in report.filled}
    assert {"first_name", "last_name", "email", "phone"} <= filled_keys
