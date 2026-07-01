"""JobFinder — Streamlit entry point (v1 UI shell).

A job *search*: pick filters and sources, hit Search, and get a fresh result list
each time (results don't accumulate). Thin UI over the ``jobfinder`` core package;
all logic lives in the package.

Run with:  uv run python -m streamlit run streamlit_app.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from jobfinder import __version__
from jobfinder.config import settings
from jobfinder.cv import CVContent, diff_cv, render_cv_bytes, tailor_cv
from jobfinder.matching import MatchFilters, Profile, rank
from jobfinder.pipeline import (
    DEFAULT_GREENHOUSE_BOARDS,
    SearchFilters,
    build_connectors,
    search,
)

SOURCE_LABELS = {
    "greenhouse": "Greenhouse (company boards)",
    "themuse": "The Muse (aggregator)",
    "adzuna": "Adzuna (UK, needs free key)",
}

st.set_page_config(page_title="JobFinder", page_icon="🧭", layout="wide")
st.title("🧭 JobFinder")
st.caption(f"Human-in-the-loop job search · v{__version__}")

# --- Sidebar: search controls -------------------------------------------------
with st.sidebar:
    st.header("Search")
    keyword = st.text_input("Keyword", "engineer", placeholder="e.g. python, designer")
    location = st.text_input("Location", "United Kingdom", placeholder="e.g. UK, London")

    st.markdown("**Sources**")
    use_greenhouse = st.checkbox("Greenhouse (company boards)", value=True)
    use_themuse = st.checkbox("The Muse (aggregator)", value=True)
    adzuna_ready = bool(settings.adzuna_app_id and settings.adzuna_app_key)
    use_adzuna = st.checkbox(
        "Adzuna (UK)" + ("" if adzuna_ready else " — add API key to enable"),
        value=adzuna_ready,
    )

    boards_raw = DEFAULT_GREENHOUSE_BOARDS
    if use_greenhouse:
        boards_text = st.text_input(
            "Greenhouse boards (comma-separated)", ", ".join(DEFAULT_GREENHOUSE_BOARDS)
        )
        boards_raw = [b.strip() for b in boards_text.split(",") if b.strip()]

    days = st.slider("Posted within (days)", 0, 180, 0, help="0 = any time")

    do_search = st.button("Search", type="primary", use_container_width=True)

# --- Run a search (replaces previous results) ---------------------------------
if do_search:
    sources = [
        name
        for name, on in (
            ("greenhouse", use_greenhouse),
            ("themuse", use_themuse),
            ("adzuna", use_adzuna),
        )
        if on
    ]
    if not sources:
        st.warning("Select at least one source.")
    else:
        since = datetime.now(timezone.utc) - timedelta(days=days) if days > 0 else None
        filters = SearchFilters(keyword=keyword, location=location, since=since)
        connectors = build_connectors(sources, location=location, greenhouse_boards=boards_raw)
        with st.spinner("Searching…"):
            st.session_state["outcome"] = search(connectors, filters)
        st.session_state["query_label"] = (
            f"“{keyword or 'any'}” in “{location or 'anywhere'}”"
        )

# --- Render results (scored against your CV, filtered, best-match first) ------
outcome = st.session_state.get("outcome")
ranked_postings = []  # used by the Tailor section below

if outcome is None:
    st.info("Set your filters in the sidebar and hit **Search** to find jobs.")
else:
    st.subheader(f"{outcome.total} results · {st.session_state.get('query_label', '')}")

    # Per-source summary, including skipped/errored sources (e.g. Adzuna w/o key).
    chips = []
    for s in outcome.sources:
        label = SOURCE_LABELS.get(s.source, s.source)
        if s.error:
            chips.append(f"⚠️ {label}: {s.error}")
        else:
            chips.append(f"✅ {label}: {s.kept} kept / {s.fetched} fetched")
    st.caption(" · ".join(chips))

    if outcome.total == 0:
        st.warning("No matches. Try a broader keyword, a different location, or more sources.")
    else:
        # Match & filter controls — scored locally against your CV, no API needed.
        c1, c2, c3 = st.columns([2, 1, 1])
        boost_kw = c1.text_input("Boost keywords", help="Extra relevant terms, comma-separated")
        exclude_kw = c1.text_input("Exclude keywords", help="Drop jobs mentioning these")
        min_score = c2.slider("Min match %", 0, 100, 0)
        entry_only = c3.checkbox("Entry-level only")
        remote_only = c3.checkbox("Remote only")

        profile = Profile.from_cv(
            CVContent.load(settings.cv_path()),
            target_keywords=[k for k in boost_kw.split(",") if k.strip()],
        )
        mfilters = MatchFilters(
            min_score=min_score,
            exclude_keywords=[k for k in exclude_kw.split(",") if k.strip()],
            require_remote=remote_only,
            entry_level_only=entry_only,
        )
        ranked = rank(profile, outcome.postings, mfilters)
        ranked_postings = [p for p, _ in ranked]

        st.caption(f"Showing {len(ranked)} of {outcome.total} after match filtering.")
        rows = [
            {
                "Match": r.score,
                "Title": p.title,
                "Company": p.company,
                "Location": p.location or "—",
                "Remote": "✅" if p.remote else "",
                "Posted": p.posted_at.date().isoformat() if p.posted_at else "—",
                "Source": p.source,
                "Link": p.url,
            }
            for p, r in ranked
        ]
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Match": st.column_config.ProgressColumn(
                    "Match", min_value=0, max_value=100, format="%d%%"
                ),
                "Link": st.column_config.LinkColumn("Link", display_text="open"),
            },
        )

st.divider()

# --- Tailor CV ----------------------------------------------------------------
st.subheader("✍️ Tailor your CV")
if not settings.anthropic_api_key:
    st.info(
        "Set `ANTHROPIC_API_KEY` in `.env` to enable CV tailoring. It rewrites your "
        "summary and bullet wording for a chosen job — never changing employers, "
        "dates, or facts — and shows you a diff before you download."
    )
else:
    master_cv = CVContent.load(settings.cv_path())
    st.caption(f"Master CV: {settings.cv_path().name} · model: {settings.anthropic_model}")

    # Offer the ranked (best-match-first) jobs from the search above.
    postings = ranked_postings
    labels = ["✏️ Paste a job description"] + [
        f"{p.title} — {p.company}" for p in postings
    ]
    choice = st.selectbox("Job to tailor for", labels)

    if choice == labels[0]:
        title = st.text_input("Job title")
        company = st.text_input("Company")
        description = st.text_area("Job description", height=180)
    else:
        picked = postings[labels.index(choice) - 1]
        title, company, description = picked.title, picked.company, picked.description
        with st.expander("Job description", expanded=False):
            st.write(description or "_(no description)_")

    if st.button("Tailor CV", type="primary"):
        if not description.strip():
            st.warning("Provide a job description to tailor against.")
        else:
            with st.spinner("Tailoring with Claude…"):
                try:
                    result = tailor_cv(
                        master_cv, title=title, company=company, description=description
                    )
                    st.session_state["tailored"] = (result, master_cv, company or "job")
                except Exception as exc:  # billing, network, API errors
                    st.session_state.pop("tailored", None)
                    st.error(f"Tailoring failed: {exc}")

    tailored_state = st.session_state.get("tailored")
    if tailored_state:
        result, master_used, comp = tailored_state
        for warning in result.warnings:
            st.warning(warning)

        changes = diff_cv(master_used, result.tailored)
        st.write(f"**{len(changes)} content change(s)** — review before using:")
        if changes:
            st.dataframe(
                pd.DataFrame(
                    [{"Field": c.path, "Before": c.before, "After": c.after} for c in changes]
                ),
                hide_index=True,
                use_container_width=True,
            )

        safe_comp = "".join(ch for ch in comp if ch.isalnum() or ch in "-_") or "job"
        c1, c2 = st.columns(2)
        c1.download_button(
            "⬇️ Tailored CV (PDF)",
            data=render_cv_bytes(result.tailored),
            file_name=f"CV_{safe_comp}.pdf",
            mime="application/pdf",
            type="primary",
        )
        c2.download_button(
            "⬇️ Master CV (PDF)",
            data=render_cv_bytes(master_used),
            file_name="CV_master.pdf",
            mime="application/pdf",
        )

with st.expander("Configuration"):
    st.write(
        {
            "adzuna_configured": bool(settings.adzuna_app_id and settings.adzuna_app_key),
            "anthropic_configured": bool(settings.anthropic_api_key),
            "anthropic_model": settings.anthropic_model,
            "cv": settings.cv_path().name,
            "database_url": settings.database_url,
        }
    )
