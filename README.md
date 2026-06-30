# JobFinder

A human-in-the-loop job-application assistant. It finds postings from legal sources,
tailors your CV per role **without changing its visual structure**, and queues each
application for your review before anything is submitted.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design and build order.

## Status

v1, in progress. Project skeleton + data model in place. Next: a job connector, then
the CV template + tailoring.

## Getting started

Requires [uv](https://docs.astral.sh/uv/).

```bash
# Install Python + dependencies into a local virtualenv
uv sync

# Copy environment template and adjust as needed
cp .env.example .env

# Launch the Streamlit app (initializes the SQLite database on first run)
uv run streamlit run streamlit_app.py
```

## Layout

```
src/jobfinder/        core package (framework-agnostic logic)
  config.py           settings from env/.env
  db.py               SQLAlchemy engine + session
  models.py           ORM models (User, CvDocument, Job, Application, SourceRun)
  schema.py           canonical pipeline shapes (RawPosting)
  connectors/         pluggable job sources (one class per source)
streamlit_app.py      v1 UI shell
tests/                tests
```
