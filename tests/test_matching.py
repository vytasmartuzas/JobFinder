"""Tests for match scoring and rule filters."""

from __future__ import annotations

from jobfinder.matching import (
    MatchFilters,
    Profile,
    passes_filters,
    rank,
    score_posting,
)
from jobfinder.schema import RawPosting

PROFILE = Profile(terms=["python", "react", "postgresql", "aws", "go"])


def _job(title: str, description: str = "", remote: bool = False) -> RawPosting:
    return RawPosting(
        source="test",
        external_id=title,
        title=title,
        company="Acme",
        description=description,
        url="https://x",
        remote=remote,
    )


def test_relevant_job_scores_higher_than_irrelevant() -> None:
    relevant = score_posting(
        PROFILE, _job("Python Engineer", "Build APIs with Python, React and PostgreSQL on AWS.")
    )
    irrelevant = score_posting(PROFILE, _job("Warehouse Operative", "Lift boxes and drive a forklift."))
    assert relevant.score > irrelevant.score
    assert irrelevant.score == 0
    assert "python" in relevant.matched


def test_title_match_weighs_more_than_description() -> None:
    in_title = score_posting(PROFILE, _job("Python Developer", "General duties."))
    in_desc = score_posting(PROFILE, _job("Developer", "Some Python involved."))
    assert in_title.score > in_desc.score


def test_word_boundary_avoids_false_positives() -> None:
    # "go" must not match inside "good"; must match "Go" as a word.
    assert score_posting(PROFILE, _job("Analyst", "A good role.")).matched == []
    assert "go" in score_posting(PROFILE, _job("Go Engineer", "Write Go.")).matched


def test_entry_level_filter_drops_senior_titles() -> None:
    f = MatchFilters(entry_level_only=True)
    senior = _job("Senior Python Engineer", "Python.")
    junior = _job("Graduate Python Engineer", "Python.")
    assert not passes_filters(senior, score_posting(PROFILE, senior), f)
    assert passes_filters(junior, score_posting(PROFILE, junior), f)


def test_exclude_keywords_and_remote_filters() -> None:
    job = _job("Python Engineer", "Requires security clearance.", remote=False)
    r = score_posting(PROFILE, job)
    assert not passes_filters(job, r, MatchFilters(exclude_keywords=["clearance"]))
    assert not passes_filters(job, r, MatchFilters(require_remote=True))
    assert passes_filters(job, r, MatchFilters())


def test_rank_sorts_and_filters() -> None:
    jobs = [
        _job("Warehouse Operative", "forklift"),
        _job("Python Engineer", "Python, React, AWS", remote=True),
        _job("Senior Python Engineer", "Python", remote=True),
    ]
    ranked = rank(PROFILE, jobs, MatchFilters(min_score=1, entry_level_only=True))
    titles = [p.title for p, _ in ranked]
    assert titles == ["Python Engineer"]  # warehouse (0 score) + senior both filtered


def test_profile_from_cv_extracts_skill_terms() -> None:
    from pathlib import Path

    from jobfinder.cv import CVContent

    example = Path(__file__).resolve().parents[1] / "cv" / "example_cv.json"
    profile = Profile.from_cv(CVContent.load(example), target_keywords=["backend"])
    assert "python" in profile.terms
    assert "backend" in profile.terms
