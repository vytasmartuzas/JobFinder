"""JobFinder — Streamlit entry point (v1 UI shell).

A job *search*: pick filters and sources, hit Search, and get a fresh result list
each time (results don't accumulate). Thin UI over the ``jobfinder`` core package;
all logic lives in the package.

Run with:  uv run python -m streamlit run streamlit_app.py
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from jobfinder import __version__
from jobfinder.config import PROJECT_ROOT, settings
from jobfinder.cv import CVContent, diff_cv, render_cv_bytes, render_cv_pdf, tailor_cv
from jobfinder.db import init_db, session_scope
from jobfinder.matching import MatchFilters, Profile, rank, score_posting
from jobfinder.models import ApplicationStatus
from jobfinder.pipeline import (
    DEFAULT_GREENHOUSE_BOARDS,
    SearchFilters,
    build_connectors,
    list_applications,
    save_application,
    search,
    set_status,
    update_tailored_content,
)
from jobfinder.schema import RawPosting

SOURCE_LABELS = {
    "greenhouse": "Greenhouse (company boards)",
    "themuse": "The Muse (aggregator)",
    "adzuna": "Adzuna (UK, needs free key)",
}

STATUS_BADGES = {
    ApplicationStatus.in_review: "🟡 in review",
    ApplicationStatus.approved: "🟢 approved",
    ApplicationStatus.submitted: "📤 submitted",
    ApplicationStatus.responded: "💬 responded",
    ApplicationStatus.rejected: "❌ rejected",
    ApplicationStatus.matched: "◻️ matched",
    ApplicationStatus.discovered: "◻️ discovered",
    ApplicationStatus.tailored: "◻️ tailored",
}

st.set_page_config(page_title="JobFinder", page_icon="🧭", layout="wide")
init_db()
st.title("🧭 JobFinder")
st.caption(f"Human-in-the-loop job search · v{__version__}")


def run_tailoring(posting: RawPosting) -> None:
    """Tailor the master CV for `posting`, stash the result, and refresh the UI."""
    if not (posting.description or "").strip():
        st.warning("This posting has no job description to tailor against.")
        return
    master_cv = CVContent.load(settings.cv_path())
    with st.spinner("Tailoring with Claude…"):
        try:
            result = tailor_cv(
                master_cv,
                title=posting.title,
                company=posting.company,
                description=posting.description,
            )
        except Exception as exc:  # billing, network, API errors
            st.session_state.pop("tailored", None)
            st.error(f"Tailoring failed: {exc}")
            return
    st.session_state["tailored"] = (result, master_cv, posting)
    st.rerun()

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
ranked_postings = []  # row-selection below maps back into this ranked list

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
        event = st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Match": st.column_config.ProgressColumn(
                    "Match", min_value=0, max_value=100, format="%d%%"
                ),
                "Link": st.column_config.LinkColumn("Link", display_text="open"),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="results_table",
        )

        sel = event.selection.rows if event else []
        selected_posting = ranked_postings[sel[0]] if sel else None
        tailor_ready = bool(settings.anthropic_api_key)

        b_col, hint_col = st.columns([1, 3])
        if b_col.button(
            "✂️ Tailor CV",
            type="primary",
            disabled=selected_posting is None or not tailor_ready,
        ):
            run_tailoring(selected_posting)
        if not tailor_ready:
            hint_col.caption("Set `ANTHROPIC_API_KEY` in `.env` to enable CV tailoring.")
        elif selected_posting is None:
            hint_col.caption("Tick a row's checkbox to tailor your CV for that job.")
        else:
            hint_col.caption(
                f"Selected: **{selected_posting.title} — {selected_posting.company}**"
            )

# --- Tailored CV result (from the ✂️ button above or the expander below) --------
tailored_state = st.session_state.get("tailored")
if tailored_state:
    st.divider()
    result, master_used, tailored_posting = tailored_state
    comp = tailored_posting.company or "job"
    st.subheader(f"✍️ Tailored CV — {tailored_posting.title} — {comp}")
    st.caption(f"Master CV: {settings.cv_path().name} · model: {settings.anthropic_model}")
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
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "⬇️ Tailored CV (PDF)",
        data=render_cv_bytes(result.tailored),
        file_name=f"CV_{safe_comp}.pdf",
        mime="application/pdf",
    )
    c2.download_button(
        "⬇️ Master CV (PDF)",
        data=render_cv_bytes(master_used),
        file_name="CV_master.pdf",
        mime="application/pdf",
    )
    if c3.button("💾 Save to review queue", type="primary"):
        match = score_posting(Profile.from_cv(master_used), tailored_posting)
        with session_scope() as db:
            save_application(
                db,
                tailored_posting,
                tailored_content_json=result.tailored.to_json(),
                match_score=float(match.score),
            )
        st.session_state.pop("tailored", None)
        st.success("Saved — it's now in the review queue below.")
        st.rerun()

st.divider()

# --- Tailor for a job found outside the search ----------------------------------
with st.expander("✏️ Tailor for a job found elsewhere (paste a description)"):
    if not settings.anthropic_api_key:
        st.info("Set `ANTHROPIC_API_KEY` in `.env` to enable CV tailoring.")
    else:
        title = st.text_input("Job title")
        company = st.text_input("Company")
        description = st.text_area("Job description", height=180)
        url = st.text_input("Job URL (optional)")
        if st.button("✂️ Tailor CV", type="primary", key="manual_tailor"):
            # A pasted JD becomes a synthetic posting so it can be saved like any other.
            digest = hashlib.sha256(
                f"{title}|{company}|{description}".encode()
            ).hexdigest()[:16]
            run_tailoring(
                RawPosting(
                    source="manual",
                    external_id=digest,
                    title=title or "Untitled role",
                    company=company or "Unknown",
                    description=description,
                    url=url,
                )
            )

st.divider()

# --- Review queue ---------------------------------------------------------------
st.subheader("📋 Review queue")
with session_scope() as db:
    apps = list_applications(db)

if not apps:
    st.info("Nothing here yet. Tailor a CV above and hit **Save to review queue**.")
else:
    master_for_diff = CVContent.load(settings.cv_path())
    active = [a for a in apps if a.status != ApplicationStatus.rejected]
    rejected = [a for a in apps if a.status == ApplicationStatus.rejected]

    for app in active:
        badge = STATUS_BADGES.get(app.status, app.status.value)
        score = f" · match {app.match_score:.0f}%" if app.match_score is not None else ""
        with st.expander(f"{badge} — {app.title} — {app.company}{score}"):
            meta = f"Saved {app.created_at:%Y-%m-%d}" if app.created_at else ""
            if app.submitted_at:
                meta += f" · submitted {app.submitted_at:%Y-%m-%d}"
            if app.url:
                meta += f" · [job posting]({app.url})"
            st.caption(meta)

            tailored_cv = (
                CVContent.from_json(app.tailored_content_json)
                if app.tailored_content_json
                else None
            )
            if tailored_cv is not None:
                changes = diff_cv(master_for_diff, tailored_cv)
                if changes:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {"Field": c.path, "Before": c.before, "After": c.after}
                                for c in changes
                            ]
                        ),
                        hide_index=True,
                        use_container_width=True,
                    )
                st.download_button(
                    "⬇️ Tailored CV (PDF)",
                    data=render_cv_bytes(tailored_cv),
                    file_name=f"CV_{app.company or 'job'}.pdf",
                    mime="application/pdf",
                    key=f"pdf_{app.id}",
                )
                with st.popover("✏️ Edit tailored content"):
                    edited = st.text_area(
                        "Tailored CV (JSON)",
                        value=app.tailored_content_json,
                        height=300,
                        key=f"edit_{app.id}",
                    )
                    if st.button("Save edits", key=f"save_edit_{app.id}"):
                        try:
                            CVContent.from_json(edited)  # validate before storing
                        except Exception as exc:
                            st.error(f"Invalid CV JSON: {exc}")
                        else:
                            with session_scope() as db:
                                update_tailored_content(db, app.id, edited)
                            st.rerun()

            notes = st.text_input("Notes", value=app.notes or "", key=f"notes_{app.id}")
            if app.status == ApplicationStatus.responded and app.response_status:
                st.write(f"**Response:** {app.response_status}")

            # Lifecycle actions, derived from the current status.
            b1, b2, b3 = st.columns(3)
            def _move(status: ApplicationStatus, **kwargs) -> None:
                with session_scope() as db:
                    set_status(db, app.id, status, notes=notes or None, **kwargs)
                st.rerun()

            if app.status == ApplicationStatus.in_review:
                if b1.button("✅ Approve", key=f"approve_{app.id}", type="primary"):
                    _move(ApplicationStatus.approved)
                if b2.button("❌ Reject", key=f"reject_{app.id}"):
                    _move(ApplicationStatus.rejected)
            elif app.status == ApplicationStatus.approved:
                if b1.button(
                    "🚀 Open & pre-fill form",
                    key=f"assist_{app.id}",
                    disabled=not app.url,
                    help="Opens the application page in your browser with your details "
                    "pre-filled and the tailored CV attached. You review and submit.",
                ):
                    cv_pdf = None
                    if tailored_cv is not None:
                        safe = (
                            "".join(
                                ch for ch in (app.company or "job") if ch.isalnum() or ch in "-_"
                            )
                            or "job"
                        )
                        cv_pdf = render_cv_pdf(
                            tailored_cv, settings.generated_dir / f"CV_{app.id}_{safe}.pdf"
                        )
                    cmd = [sys.executable, "-m", "jobfinder.submit", app.url]
                    if cv_pdf is not None:
                        cmd += ["--cv", str(cv_pdf)]
                    subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))
                    st.info(
                        "Browser opening… review the pre-filled form, submit it yourself, "
                        "then come back and **Mark submitted**."
                    )
                if b2.button("📤 Mark submitted", key=f"submit_{app.id}", type="primary"):
                    _move(ApplicationStatus.submitted)
                if b3.button("❌ Reject", key=f"reject_{app.id}"):
                    _move(ApplicationStatus.rejected)
            elif app.status == ApplicationStatus.submitted:
                response = b1.text_input(
                    "Response (e.g. interview, offer, rejection)", key=f"resp_{app.id}"
                )
                if b2.button("💬 Record response", key=f"respond_{app.id}", type="primary"):
                    _move(ApplicationStatus.responded, response_status=response or "responded")

    if rejected:
        with st.expander(f"❌ Rejected ({len(rejected)})"):
            for app in rejected:
                st.write(f"- {app.title} — {app.company}")

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
