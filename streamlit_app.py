"""JobFinder — Streamlit entry point (v1 UI shell).

Thin UI over the ``jobfinder`` core package. All logic lives in the package, so
swapping this for a FastAPI/React frontend in v2 means replacing this file, not
rewriting the app.

Run with:  uv run python -m streamlit run streamlit_app.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from jobfinder import __version__
from jobfinder.config import settings
from jobfinder.connectors import GreenhouseConnector
from jobfinder.db import init_db, session_scope
from jobfinder.models import Application, Job, User
from jobfinder.pipeline import run_connector

# A few public Greenhouse boards to start from; users can edit the list in the UI.
DEFAULT_BOARDS = "stripe, figma, databricks, anthropic, duolingo"

st.set_page_config(page_title="JobFinder", page_icon="🧭", layout="wide")
init_db()

st.title("🧭 JobFinder")
st.caption(f"Human-in-the-loop job-application assistant · v{__version__}")

# --- Sidebar: ingest controls -------------------------------------------------
with st.sidebar:
    st.header("Fetch jobs")
    st.caption("Source: Greenhouse public boards (no API key needed).")
    boards_raw = st.text_input("Company board tokens (comma-separated)", DEFAULT_BOARDS)
    query = st.text_input("Keyword filter (optional)", "engineer")
    days = st.slider("Only postings newer than (days)", 0, 180, 0,
                     help="0 = no date filter")

    if st.button("Fetch & ingest", type="primary"):
        boards = [b.strip() for b in boards_raw.split(",") if b.strip()]
        since = (
            datetime.now(timezone.utc) - timedelta(days=days) if days > 0 else None
        )
        if not boards:
            st.warning("Enter at least one board token.")
        else:
            with st.spinner(f"Fetching from {len(boards)} board(s)…"):
                try:
                    with session_scope() as session:
                        stats = run_connector(
                            session,
                            GreenhouseConnector(boards),
                            query=query,
                            since=since,
                        )
                    st.success(
                        f"Found {stats.found} · added {stats.new} new · "
                        f"{stats.duplicates} already known."
                    )
                except Exception as exc:  # surface connector/network errors in the UI
                    st.error(f"Fetch failed: {exc}")

# --- Metrics ------------------------------------------------------------------
with session_scope() as session:
    counts = {
        "Users": session.query(User).count(),
        "Jobs ingested": session.query(Job).count(),
        "Applications": session.query(Application).count(),
    }
cols = st.columns(len(counts))
for col, (label, value) in zip(cols, counts.items()):
    col.metric(label, value)

st.divider()

# --- Ingested jobs table ------------------------------------------------------
st.subheader("Ingested jobs")
with session_scope() as session:
    jobs = (
        session.query(Job)
        .order_by(Job.posted_at.is_(None), Job.posted_at.desc())
        .limit(200)
        .all()
    )

if not jobs:
    st.info("No jobs yet. Use **Fetch jobs** in the sidebar to pull some in.")
else:
    rows = [
        {
            "Title": j.title,
            "Company": j.company,
            "Location": j.location or "—",
            "Remote": "✅" if j.remote else "",
            "Posted": j.posted_at.date().isoformat() if j.posted_at else "—",
            "Source": j.source,
            "Link": j.url,
        }
        for j in jobs
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={"Link": st.column_config.LinkColumn("Link", display_text="open")},
    )
    st.caption(f"Showing {len(jobs)} most recent (newest postings first).")

with st.expander("Configuration"):
    st.write({"database_url": settings.database_url, "generated_dir": str(settings.generated_dir)})
