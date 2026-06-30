# JobFinder — Architecture

A job-application assistant. It pulls job postings from legal sources, filters them
against your criteria, tailors your CV (and cover letter) per posting **without
changing the CV's visual structure**, and presents each one in a review queue where
you approve, edit, or reject before anything is submitted.

> **Design principle: human-in-the-loop.** The system does the finding, matching, and
> drafting. A human approves the final submission. This keeps applications high-quality
> and keeps accounts off the wrong side of job-board Terms of Service.

---

## Goals

- **Now (v1):** make it work end-to-end for one user (you), running locally.
- **Later (v2):** a proper multi-user web app you can hand to friends/family.

Every v1 decision below is made so it can scale to v2 without a rewrite — the data is
already scoped per-user, the CV/content lives in the database rather than in local
files, and the tailoring/rendering logic is stateless.

---

## High-level flow

```
 ┌──────────────┐    ┌──────────┐    ┌─────────┐    ┌──────────┐    ┌────────────┐    ┌────────────┐
 │ Job Sources  │ →  │ Ingest & │ →  │ Match & │ →  │ Tailor   │ →  │ Review     │ →  │ Submit     │
 │ (APIs/feeds) │    │ Normalize│    │ Filter  │    │ (LLM)    │    │ Queue (UI) │    │ (assisted) │
 └──────────────┘    └──────────┘    └─────────┘    └──────────┘    └────────────┘    └────────────┘
                          │               │              │               │                  │
                          └───────────────┴──────────────┴───────────────┴──────────────────┘
                                                    Database
```

Application lifecycle (status field on each application):

```
discovered → matched → tailored → in_review → approved → submitted → responded
                 └→ rejected (at any review step)
```

---

## Components

### 1. Job Sources (legal, ToS-safe)

Prefer official APIs and feeds over scraping ToS-restricted boards (LinkedIn, Indeed).

| Source            | Type        | Notes                                        |
|-------------------|-------------|----------------------------------------------|
| Greenhouse        | Public API  | `boards-api.greenhouse.io/v1/boards/{co}/jobs` |
| Lever             | Public API  | `api.lever.co/v0/postings/{co}`              |
| Ashby             | Public API  | Public job board JSON                         |
| Workday           | Public feed | Per-company tenant URLs                        |
| Adzuna            | API (key)   | Aggregator, generous free tier                |
| Arbeitnow         | API         | Free, EU-friendly                             |
| RemoteOK / Jobicy | API/JSON    | Remote roles                                  |
| We Work Remotely  | RSS         | Remote roles                                  |

Each source is a **connector** implementing a common interface:

```
fetch(query, since) -> list[RawPosting]
```

This makes sources pluggable — adding one is writing one class, not touching the pipeline.

### 2. Ingest & Normalize

Connectors emit source-specific shapes; the ingester maps each into the canonical
`Job` record and de-duplicates (by `(source, external_id)` and a content hash to catch
the same job cross-posted on multiple sources).

Canonical `Job`: `id, source, external_id, title, company, location, remote,
description, url, posted_at, ingested_at, content_hash`.

### 3. Match & Filter

Runs **before** any LLM call to keep cost and review volume down.

- Stage 1 — cheap rules: keyword include/exclude, location/remote, seniority.
- Stage 2 — semantic: embed the job description, compare against your profile/target
  roles, keep above a similarity threshold.

Output: a `match_score` and a boolean `passed`. Only passing jobs become applications.

### 4. CV model & tailoring — *the core design decision*

**Do not edit the PDF directly.** Editing a PDF's text reflows layout and breaks the
"same structure" requirement. Instead:

- **One-time setup:** rebuild your CV as a **fixed template** (HTML+CSS, or LaTeX) plus a
  separate **structured content document** (JSON/YAML): summary, experience bullets,
  skills, education, etc.
- **Per application:** the LLM only rewrites *content fields* within the existing schema
  — rephrase the summary, reorder/select which bullets and skills to surface for this
  job. It **cannot** alter the template, so every rendered PDF is structurally identical
  to your master.
- **Render:** content + template → PDF via a renderer (WeasyPrint for HTML, or
  Playwright print-to-PDF; Tectonic/latexmk if LaTeX).

```
 master_cv_content (JSON) ──┐
                            ├──► LLM tailor(job) ──► tailored_content (JSON) ──► render(template) ──► PDF
 job.description ───────────┘
```

Cover letters work the same way: a fixed letter template + LLM-generated body.

A **schema validator** runs on the tailored JSON before rendering — same keys, same
field count where structure must be preserved — so the LLM can't silently add/drop
sections.

### 5. Review Queue (human-in-the-loop UI)

The control point. For each tailored application, show:

- the job posting,
- the rendered CV PDF (and cover letter),
- a **diff** of tailored content vs. your master CV,
- actions: **approve / edit / reject**.

Nothing is submitted without an explicit approve here.

### 6. Submission (assisted, not fully autonomous)

- Where a legal API exists, submit through it.
- Otherwise, Playwright opens the official application form and pre-fills it, then
  **pauses for you to review and click submit**.
- Record outcome back onto the application (`submitted_at`, confirmation/ref).

### 7. Tracking

Dashboard over all applications and their lifecycle status, with notes and follow-up
reminders.

---

## Data model (initial)

Scoped to a `user` from day one so v2 multi-user is a deployment change, not a redesign.

- **user** — `id, name, email, created_at` (v1: a single seeded row).
- **cv_document** — `id, user_id, name, template_ref, content_json, is_master`.
- **job** — canonical posting (fields above).
- **application** — `id, user_id, job_id, cv_document_id, status, match_score,
  tailored_content_json, cover_letter_json, rendered_cv_path, created_at, submitted_at,
  response_status, notes`.
- **source_run** — bookkeeping per connector fetch (for incremental/`since` pulls).

---

## Suggested stack

| Concern        | v1 (local)                    | v2 (multi-user web)                |
|----------------|-------------------------------|-----------------------------------|
| Language       | Python                        | same                              |
| API/backend    | FastAPI                       | same (add auth)                   |
| DB             | SQLite                        | Postgres                          |
| Web UI         | React/Next.js (or Streamlit for a fast v1 review queue) | React/Next.js |
| Job connectors | `httpx` + per-source classes  | same, + scheduled workers         |
| Tailoring      | Claude API (`claude-sonnet-5`)| same                              |
| Embeddings     | for match/filter              | same                              |
| Rendering      | WeasyPrint (HTML→PDF)         | same                              |
| Form assist    | Playwright                    | same                              |
| Auth (v2 only) | —                             | sessions/OAuth, per-user data     |

> FastAPI from the start (even if the v1 UI is thin) means the v2 web frontend is a UI
> swap, not a backend rewrite.

---

## Legal / safety guardrails

- Only ingest from sources whose ToS permit API/feed access; no scraping of boards that
  forbid it.
- Respect rate limits and `robots.txt`; cache results.
- Human approves every submission — no blind auto-apply.
- Never fabricate credentials/experience during tailoring (rephrase and reprioritize
  only; system prompt constrains this and the diff view makes any drift visible).

---

## Build order (one step at a time)

1. **Project skeleton** — repo layout, FastAPI app, SQLite, data models/migrations.
2. **One job connector** — e.g. Greenhouse — fetch → normalize → store. Prove the pipe.
3. **CV template + content model** — convert your PDF to template + JSON; render to PDF.
4. **Tailoring** — LLM rewrites content JSON for a job; schema validation; re-render.
5. **Match & filter** — rules first, then embeddings.
6. **Review queue UI** — job + PDF + diff + approve/reject.
7. **Submission assist** — Playwright pre-fill with manual submit.
8. **Tracking dashboard** — lifecycle view + follow-ups.
9. **More connectors** — add sources behind the connector interface.
10. **v2 multi-user** — auth, Postgres, per-user isolation, deploy.

We tackle these in order, getting each working before moving on.
```
