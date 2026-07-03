"""Submission assist — open a job's application form pre-filled, never auto-submit.

Playwright drives the *system-installed* Edge/Chrome (no bundled Chromium, which
this machine's Application Control policy could block). It best-effort fills the
common ATS fields (name, email, phone, links, CV upload) from the candidate's
master CV, then leaves the browser open: the human reviews and clicks submit.

Run standalone (Streamlit launches it as a detached subprocess so the UI never
blocks while the browser is open):

    python -m jobfinder.submit <url> [--cv path/to/tailored.pdf]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .cv.content import CVContent

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d ()\-]{7,}\d")

# Browser channels to try, most preferred first. All are system-installed,
# signed binaries (WDAC-safe); Playwright's own Chromium is the last resort.
BROWSER_CHANNELS: tuple[str | None, ...] = ("msedge", "chrome", None)


@dataclass
class ApplicantProfile:
    """The candidate facts used to fill application forms."""

    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""

    @classmethod
    def from_cv(cls, cv: CVContent) -> ApplicantProfile:
        p = cls()
        name = cv.name.strip()
        p.full_name = name.title() if name.isupper() else name
        parts = p.full_name.split()
        if parts:
            p.first_name, p.last_name = parts[0], parts[-1]

        for line in cv.contact_lines:
            if not p.email and (m := _EMAIL.search(line)):
                p.email = m.group(0)
            if not p.phone and (m := _PHONE.search(line)):
                p.phone = m.group(0).strip()
            for segment in (s.strip() for s in line.split("|")):
                low = segment.lower()
                if "linkedin.com" in low and not p.linkedin:
                    p.linkedin = _as_url(segment)
                elif "github.com" in low and not p.github:
                    p.github = _as_url(segment)
                elif (
                    not p.location
                    and ", " in segment
                    and "@" not in segment
                    and not any(ch.isdigit() for ch in segment)
                    and len(segment) < 40
                ):
                    p.location = segment
        return p


def _as_url(text: str) -> str:
    text = text.strip()
    return text if text.startswith("http") else f"https://{text}"


# Descriptor patterns for common ATS fields, checked in order — the first match
# wins, so specific patterns (first/last name) come before the generic "name".
_FIELD_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"e[-_ ]?mail")),
    ("phone", re.compile(r"phone|mobile|\btel\b|telephone")),
    ("first_name", re.compile(r"first[-_ ]?name|firstname|given[-_ ]?name|forename")),
    ("last_name", re.compile(r"last[-_ ]?name|lastname|sur[-_ ]?name|family[-_ ]?name")),
    ("linkedin", re.compile(r"linked[-_ ]?in")),
    ("github", re.compile(r"github|portfolio|website")),
    ("location", re.compile(r"location|city|town")),
    ("full_name", re.compile(r"full[-_ ]?name|your[-_ ]?name|\bname\b")),
]
# Descriptors that look like a name field but aren't the candidate's name.
_NAME_BLOCKLIST = re.compile(r"user[-_ ]?name|company|employer|school|file[-_ ]?name")

_UPLOAD_HINT = re.compile(r"resume|\bcv\b|curriculum|upload|attach")


def classify_field(descriptor: str) -> str | None:
    """Map a form field's combined attributes/label text to a profile key."""
    d = descriptor.lower()
    for key, pattern in _FIELD_RULES:
        if pattern.search(d):
            if key in ("full_name", "first_name", "last_name") and _NAME_BLOCKLIST.search(d):
                return None
            return key
    return None


@dataclass
class PrefillReport:
    filled: list[tuple[str, str]] = field(default_factory=list)
    uploaded: bool = False

    def summary(self) -> str:
        lines = [f"  {k:12} = {v}" for k, v in self.filled]
        if self.uploaded:
            lines.append("  CV file attached")
        return "\n".join(lines) or "  (no recognisable fields found)"


def _descriptor(el, frame) -> str:
    """Combine a field's identifying attributes + its associated label text."""
    parts = [
        el.get_attribute("name") or "",
        el.get_attribute("id") or "",
        el.get_attribute("placeholder") or "",
        el.get_attribute("aria-label") or "",
        el.get_attribute("autocomplete") or "",
    ]
    try:
        el_id = el.get_attribute("id")
        if el_id:
            label = frame.query_selector(f'label[for="{el_id}"]')
            if label:
                parts.append(label.inner_text())
    except Exception:
        pass
    return " ".join(parts)


def prefill_frame(frame, profile: ApplicantProfile, cv_pdf: Path | None, report: PrefillReport) -> None:
    """Best-effort fill of one frame's visible inputs. Never raises."""
    try:
        elements = frame.query_selector_all(
            'input[type="text"], input[type="email"], input[type="tel"], '
            "input:not([type]), textarea"
        )
    except Exception:
        return

    for el in elements:
        try:
            if not el.is_visible() or not el.is_enabled() or el.input_value():
                continue
            key = classify_field(_descriptor(el, frame))
            value = getattr(profile, key, "") if key else ""
            if value:
                el.fill(value)
                report.filled.append((key, value))
        except Exception:
            continue

    if cv_pdf is not None and not report.uploaded:
        try:
            for el in frame.query_selector_all('input[type="file"]'):
                context = _descriptor(el, frame) + " " + (el.get_attribute("accept") or "")
                if _UPLOAD_HINT.search(context.lower()):
                    el.set_input_files(str(cv_pdf))
                    report.uploaded = True
                    break
        except Exception:
            pass


def run_assist(url: str, profile: ApplicantProfile, cv_pdf: Path | None = None) -> None:
    """Open `url` in a visible browser, pre-fill, and wait until the user closes it."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = None
        for channel in BROWSER_CHANNELS:
            try:
                browser = pw.chromium.launch(channel=channel, headless=False)
                break
            except Exception:
                continue
        if browser is None:
            print("Could not launch a browser (Edge/Chrome not found).", file=sys.stderr)
            sys.exit(1)

        page = browser.new_page()
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)  # let ATS scripts render the form

        report = PrefillReport()
        for frame in page.frames:  # main frame + embedded ATS iframes
            prefill_frame(frame, profile, cv_pdf, report)

        print("Pre-filled:")
        print(report.summary())
        print("\nReview the form in the browser, then submit it yourself.")
        print("Close the browser window when done.")

        try:
            while browser.is_connected() and browser.contexts and any(
                ctx.pages for ctx in browser.contexts
            ):
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        try:
            browser.close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> None:
    from .config import settings

    parser = argparse.ArgumentParser(description="Open a job application form pre-filled.")
    parser.add_argument("url", help="The job application page URL")
    parser.add_argument("--cv", type=Path, default=None, help="Tailored CV PDF to attach")
    args = parser.parse_args(argv)

    profile = ApplicantProfile.from_cv(CVContent.load(settings.cv_path()))
    run_assist(args.url, profile, args.cv)


if __name__ == "__main__":
    main()
