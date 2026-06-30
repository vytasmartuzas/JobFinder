"""Location matching, used as the authoritative location filter for searches.

Job-board location strings are messy free text ("London, UK", "London - United
Kingdom", "Dublin OR London", "Flexible / Remote"). A naive substring test is wrong
in two ways: short codes like "uk" would match "Ukraine", and "United Kingdom" has no
"uk" substring at all. So we expand a query into a set of aliases and match each with
the right granularity (word-boundary for short codes, substring for the rest).
"""

from __future__ import annotations

import re

# Each group lists interchangeable names for one place. Querying any member matches
# any other. Cities are intentionally included so "uk" also catches "London, UK".
_ALIAS_GROUPS: list[list[str]] = [
    [
        "united kingdom", "uk", "u.k.", "great britain", "britain", "gb",
        "england", "scotland", "wales", "northern ireland",
        "london", "manchester", "birmingham", "edinburgh", "glasgow",
        "bristol", "leeds", "cambridge", "oxford", "cardiff", "belfast",
    ],
    ["united states", "usa", "u.s.", "us", "america"],
    ["remote", "anywhere", "flexible"],
]

# Map every alias to the full set it belongs to, for O(1) expansion.
_ALIAS_INDEX: dict[str, frozenset[str]] = {}
for _group in _ALIAS_GROUPS:
    _frozen = frozenset(_group)
    for _name in _group:
        _ALIAS_INDEX[_name] = _frozen


def expand_location_query(query: str) -> set[str]:
    """Return the query plus any known aliases (e.g. "uk" -> united kingdom, london…)."""
    q = query.strip().lower()
    if not q:
        return set()
    terms = set(_ALIAS_INDEX.get(q, frozenset()))
    terms.add(q)
    return terms


def _term_in(term: str, text: str) -> bool:
    # Short codes (<= 3 chars: uk, us, gb) need word boundaries so "uk" doesn't
    # match "Ukraine"; longer names are safe as plain substrings.
    if len(term) <= 3:
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


def location_matches(location: str | None, query: str) -> bool:
    """True if `location` satisfies the `query` (empty query matches everything)."""
    terms = expand_location_query(query)
    if not terms:
        return True
    if not location:
        return False
    loc = location.lower()
    return any(_term_in(t, loc) for t in terms)
