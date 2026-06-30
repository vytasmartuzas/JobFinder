"""Tests for location matching — the authoritative location filter."""

from __future__ import annotations

import pytest

from jobfinder.locations import expand_location_query, location_matches


@pytest.mark.parametrize(
    "location",
    [
        "London, UK",
        "London - United Kingdom",
        "Manchester, England",
        "Edinburgh, Scotland",
        "Remote - United Kingdom",
    ],
)
def test_uk_query_matches_uk_locations(location: str) -> None:
    assert location_matches(location, "United Kingdom")
    assert location_matches(location, "UK")


@pytest.mark.parametrize("location", ["Berlin, Germany", "New York, NY", "Kyiv, Ukraine"])
def test_uk_query_rejects_non_uk(location: str) -> None:
    assert not location_matches(location, "UK")


def test_uk_short_code_does_not_match_ukraine() -> None:
    # The classic false positive: "uk" as a substring of "Ukraine".
    assert not location_matches("Kyiv, Ukraine", "uk")


def test_empty_query_matches_everything() -> None:
    assert location_matches("anywhere at all", "")
    assert location_matches(None, "")


def test_missing_location_fails_a_specific_query() -> None:
    assert not location_matches(None, "London")


def test_expand_includes_aliases() -> None:
    expanded = expand_location_query("uk")
    assert "united kingdom" in expanded and "london" in expanded
