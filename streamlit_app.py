"""JobFinder — Streamlit entry point (v1 UI shell).

This is intentionally thin: it imports the core ``jobfinder`` package and renders
status. Real screens (review queue, dashboard) get added in later build steps. All
logic lives in the package, so swapping this for a FastAPI/React frontend in v2 means
replacing this file, not rewriting the app.

Run with:  uv run streamlit run streamlit_app.py
"""

from __future__ import annotations

import streamlit as st

from jobfinder import __version__
from jobfinder.config import settings
from jobfinder.db import init_db, session_scope
from jobfinder.models import Application, Job, User

st.set_page_config(page_title="JobFinder", page_icon="🧭", layout="wide")

# Ensure the database and local directories exist before anything reads them.
init_db()

st.title("🧭 JobFinder")
st.caption(f"Human-in-the-loop job-application assistant · v{__version__}")

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
st.subheader("Status")
st.success("Core package loaded and database initialized.")
st.write(
    "Skeleton is in place. Next build steps add: a job connector, the CV "
    "template + tailoring, matching, and the review queue."
)

with st.expander("Configuration"):
    st.write({"database_url": settings.database_url, "generated_dir": str(settings.generated_dir)})
