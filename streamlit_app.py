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

# --- Render results -----------------------------------------------------------
outcome = st.session_state.get("outcome")

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
        rows = [
            {
                "Title": p.title,
                "Company": p.company,
                "Location": p.location or "—",
                "Remote": "✅" if p.remote else "",
                "Posted": p.posted_at.date().isoformat() if p.posted_at else "—",
                "Source": p.source,
                "Link": p.url,
            }
            for p in outcome.postings
        ]
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Link": st.column_config.LinkColumn("Link", display_text="open")
            },
        )

with st.expander("Configuration"):
    st.write(
        {
            "adzuna_configured": bool(settings.adzuna_app_id and settings.adzuna_app_key),
            "database_url": settings.database_url,
        }
    )
