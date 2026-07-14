"""Tests for the local HTTP API (browser-extension backend).

No real LLM calls — tailor_cv is monkeypatched with a fake that goes through
the same enforce_invariants safety layer the real path uses.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def server(tmp_path, monkeypatch):
    """The server module rebuilt against a fresh temp database."""
    monkeypatch.setenv("JOBFINDER_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from jobfinder import config, db as db_module, server as server_module

    importlib.reload(config)
    importlib.reload(db_module)
    return importlib.reload(server_module)


@pytest.fixture()
def client(server, monkeypatch):
    from jobfinder.cv.tailor import enforce_invariants

    def fake_tailor(master, *, title, company, description, client=None, model=None):
        proposed = master.model_copy(deep=True)
        proposed.summary = f"Tailored for {title} at {company}."
        return enforce_invariants(master, proposed)

    monkeypatch.setattr(server, "tailor_cv", fake_tailor)
    return TestClient(server.app)


def _payload(**overrides) -> dict:
    payload = {
        "title": "Backend Engineer",
        "company": "Acme",
        "description": "Python APIs on AWS.",
        "url": "https://jobs.example.com/backend-engineer",
    }
    payload.update(overrides)
    return payload


def test_health_reports_configuration(client) -> None:
    body = client.get("/health").json()
    assert body["app"] == "jobfinder"
    assert body["anthropic_configured"] is True
    assert body["model"]


def test_tailor_saves_application_and_returns_diff(client) -> None:
    resp = client.post("/tailor", json=_payload())
    assert resp.status_code == 200
    body = resp.json()

    assert isinstance(body["application_id"], int)
    assert isinstance(body["match_score"], float)
    changed_fields = {c["field"] for c in body["changes"]}
    assert "Summary" in changed_fields

    pdf = client.get(body["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_tailor_rejects_empty_description(client) -> None:
    assert client.post("/tailor", json=_payload(description="  ")).status_code == 422


def test_retailoring_same_url_updates_one_application(client, server) -> None:
    first = client.post("/tailor", json=_payload()).json()
    second = client.post("/tailor", json=_payload()).json()
    assert first["application_id"] == second["application_id"]

    from jobfinder.db import session_scope
    from jobfinder.models import Application

    with session_scope() as db:
        assert db.query(Application).count() == 1


def test_pdf_404_for_unknown_application(client) -> None:
    assert client.get("/applications/9999/pdf").status_code == 404
