"""Tests for CV tailoring: invariant enforcement, diff, and the wired call.

No real API calls — a fake client returns a crafted (and deliberately misbehaving)
proposal so we can prove the safety layer holds immutable facts fixed.
"""

from __future__ import annotations

from pathlib import Path

from jobfinder.cv import CVContent, diff_cv, tailor_cv
from jobfinder.cv.tailor import enforce_invariants

EXAMPLE = Path(__file__).resolve().parents[1] / "cv" / "example_cv.json"


def _proposal_that_cheats(master: CVContent) -> CVContent:
    """A proposal that legitimately rewrites text but also tries to alter facts."""
    data = master.model_copy(deep=True)
    data.summary = "Backend-focused engineer tailored for this role."
    # Legit: rephrase the first experience bullets.
    data.experience[0].bullets = ["Rephrased achievement emphasising Python and APIs."]
    # Cheating: change an employer name, a date, and inject a fake skill category.
    data.experience[0].organization = "FANCIER NAME LTD"
    data.experience[1].dates = "9999 - 9999"
    data.skills = [data.skills[-1]] + data.skills[:-1]  # reorder (allowed)
    data.skills[0].items = "Rust, Go, Kubernetes, fabricated skills"  # cheating
    data.name = "SOMEONE ELSE"
    return data


def test_enforce_invariants_holds_facts_but_keeps_rewrites() -> None:
    master = CVContent.load(EXAMPLE)
    result = enforce_invariants(master, _proposal_that_cheats(master))
    t = result.tailored

    # Rewrites are kept.
    assert t.summary == "Backend-focused engineer tailored for this role."
    assert t.experience[0].bullets == ["Rephrased achievement emphasising Python and APIs."]

    # Immutable facts are restored from master.
    assert t.name == master.name
    assert t.experience[0].organization == master.experience[0].organization
    assert t.experience[1].dates == master.experience[1].dates

    # Skills: reordering allowed, but items come from master verbatim (no fabrication).
    assert t.skills[0].category == master.skills[-1].category
    assert {s.category for s in t.skills} == {s.category for s in master.skills}
    assert t.skills[0].items == master.skills[-1].items  # not the injected fake items


def test_diff_reports_only_changed_text() -> None:
    master = CVContent.load(EXAMPLE)
    result = enforce_invariants(master, _proposal_that_cheats(master))
    changes = {c.path: c for c in diff_cv(master, result.tailored)}

    assert "Summary" in changes
    assert changes["Summary"].after == "Backend-focused engineer tailored for this role."
    # An employer-name change was reverted, so it must NOT show up as a diff.
    assert not any("FANCIER NAME" in c.after for c in changes.values())


def test_tailor_cv_uses_injected_client_and_enforces() -> None:
    master = CVContent.load(EXAMPLE)

    class _FakeMessages:
        def parse(self, **kwargs):
            assert kwargs["output_format"] is CVContent
            class _Resp:
                parsed_output = _proposal_that_cheats(master)
            return _Resp()

    class _FakeClient:
        messages = _FakeMessages()

    result = tailor_cv(
        master,
        title="Backend Engineer",
        company="Acme",
        description="Python APIs on AWS.",
        client=_FakeClient(),
    )
    # Went through enforce_invariants: cheat reverted, rewrite kept.
    assert result.tailored.name == master.name
    assert result.tailored.summary == "Backend-focused engineer tailored for this role."
