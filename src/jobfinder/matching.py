"""Match & filter — score how well a job fits the candidate, before tailoring.

This is the cheap stage that narrows the firehose so LLM tailoring is only spent
on relevant roles. It's fully local (no API, no embeddings): the candidate's CV
becomes a ``Profile`` of skill/role terms, and each posting is scored by weighted
term overlap (title matches count more), then passed through hard-rule filters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cv.content import CVContent
from .schema import RawPosting

# Split skill lists like "Linux (Raspberry Pi OS, Ubuntu)" into clean discrete
# terms — also break on slashes, parentheses, and ampersands.
_SPLIT = re.compile(r"[,/;()&]| and ")
_STOPWORDS = {
    "and", "or", "the", "for", "with", "of", "in", "to", "a", "an",
    "environments", "hosting", "using", "based",
}
# Title words that mark a role as too senior for an entry-level search.
_SENIOR = ["senior", "lead", "principal", "staff", "head", "director", "vp",
           "chief", "manager", "architect"]

# Match a term as a whole token: bounded by non-alphanumerics. Handles "node.js",
# "c++" reasonably and stops "go" from matching inside "good".
def _contains(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


@dataclass
class Profile:
    """The candidate's matchable terms (skills, role/target keywords)."""

    terms: list[str] = field(default_factory=list)

    @classmethod
    def from_cv(
        cls,
        cv: CVContent,
        *,
        target_keywords: list[str] | None = None,
    ) -> Profile:
        terms: set[str] = set()
        for row in cv.skills:
            for piece in _SPLIT.split(row.items):
                t = piece.strip().lower()
                # Keep concrete skills; drop stopwords and long descriptive phrases.
                if 2 <= len(t) and t not in _STOPWORDS and len(t.split()) <= 3:
                    terms.add(t)
        for kw in target_keywords or []:
            t = kw.strip().lower()
            if t:
                terms.add(t)
        return cls(terms=sorted(terms))


@dataclass
class MatchResult:
    score: int  # 0-100
    matched: list[str] = field(default_factory=list)


@dataclass
class MatchFilters:
    min_score: int = 0
    exclude_keywords: list[str] = field(default_factory=list)
    require_remote: bool = False
    entry_level_only: bool = False


def score_posting(profile: Profile, posting: RawPosting) -> MatchResult:
    """Weighted term-overlap score (title matches weigh 3x description matches)."""
    title = posting.title.lower()
    desc = posting.description.lower()
    matched: list[str] = []
    weight = 0
    for term in profile.terms:
        in_title = _contains(title, term)
        in_desc = in_title or _contains(desc, term)
        if in_title or in_desc:
            matched.append(term)
            weight += 3 if in_title else 1
    return MatchResult(score=min(100, weight * 7), matched=matched)


def passes_filters(posting: RawPosting, result: MatchResult, filters: MatchFilters) -> bool:
    if result.score < filters.min_score:
        return False
    if filters.require_remote and not posting.remote:
        return False
    haystack = f"{posting.title}\n{posting.description}".lower()
    if any(_contains(haystack, kw.strip().lower()) for kw in filters.exclude_keywords if kw.strip()):
        return False
    if filters.entry_level_only:
        title = posting.title.lower()
        if any(_contains(title, term) for term in _SENIOR):
            return False
    return True


def rank(
    profile: Profile,
    postings: list[RawPosting],
    filters: MatchFilters | None = None,
) -> list[tuple[RawPosting, MatchResult]]:
    """Score, filter, and sort postings best-match-first."""
    filters = filters or MatchFilters()
    scored = [(p, score_posting(profile, p)) for p in postings]
    kept = [(p, r) for p, r in scored if passes_filters(p, r, filters)]
    kept.sort(key=lambda pr: pr[1].score, reverse=True)
    return kept
