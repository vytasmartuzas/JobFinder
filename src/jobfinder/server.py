"""Local HTTP API — the backend for the browser extension (and future v2 UI).

Binds to 127.0.0.1 only. The extension grabs the job page's title/company/
description, POSTs it to /tailor, and gets back the safety-checked diff,
warnings, and a link to the rendered PDF; the application lands in the same
review queue the Streamlit app shows. Nothing here bypasses the invariant
layer — it is the same tailor -> enforce -> save pipeline behind a socket.

Run with:  python -m jobfinder.server
"""

from __future__ import annotations

import hashlib

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from . import __version__
from .config import settings
from .cv import CVContent, diff_cv, render_cv_bytes, tailor_cv
from .db import init_db, session_scope
from .matching import Profile, score_posting
from .pipeline import list_applications, save_application
from .schema import RawPosting


class TailorRequest(BaseModel):
    title: str = ""
    company: str = ""
    description: str
    url: str = ""


class FieldChangeOut(BaseModel):
    field: str
    before: str
    after: str


class TailorResponse(BaseModel):
    application_id: int
    match_score: float
    warnings: list[str]
    changes: list[FieldChangeOut]
    pdf_url: str


def create_app() -> FastAPI:
    api = FastAPI(title="JobFinder local API", version=__version__)
    # The server is loopback-only; extension origins vary per install
    # (chrome-extension://<id>), so allow any origin rather than pinning one.
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    init_db()

    @api.get("/health")
    def health() -> dict:
        return {
            "app": "jobfinder",
            "version": __version__,
            "anthropic_configured": bool(settings.anthropic_api_key),
            "model": settings.anthropic_model,
            "cv": settings.cv_path().name,
        }

    @api.post("/tailor", response_model=TailorResponse)
    def tailor(req: TailorRequest) -> TailorResponse:
        if not req.description.strip():
            raise HTTPException(422, "description must not be empty")
        if not settings.anthropic_api_key:
            raise HTTPException(503, "ANTHROPIC_API_KEY is not configured in .env")

        master = CVContent.load(settings.cv_path())
        # Same job page -> same external_id, so re-tailoring updates the one
        # existing application instead of piling up duplicates.
        digest_basis = req.url or f"{req.title}|{req.company}|{req.description}"
        posting = RawPosting(
            source="extension",
            external_id=hashlib.sha256(digest_basis.encode()).hexdigest()[:16],
            title=req.title or "Untitled role",
            company=req.company or "Unknown",
            description=req.description,
            url=req.url,
        )

        try:
            result = tailor_cv(
                master,
                title=posting.title,
                company=posting.company,
                description=req.description,
            )
        except Exception as exc:  # billing, network, API errors
            raise HTTPException(502, f"tailoring failed: {exc}") from exc

        match = score_posting(Profile.from_cv(master), posting)
        with session_scope() as db:
            app_id = save_application(
                db,
                posting,
                tailored_content_json=result.tailored.to_json(),
                match_score=float(match.score),
            ).id

        return TailorResponse(
            application_id=app_id,
            match_score=float(match.score),
            warnings=result.warnings,
            changes=[
                FieldChangeOut(field=c.path, before=c.before, after=c.after)
                for c in diff_cv(master, result.tailored)
            ],
            pdf_url=f"/applications/{app_id}/pdf",
        )

    @api.get("/applications/{app_id}/pdf")
    def application_pdf(app_id: int) -> Response:
        with session_scope() as db:
            view = next((v for v in list_applications(db) if v.id == app_id), None)
        if view is None or not view.tailored_content_json:
            raise HTTPException(404, "no tailored CV for that application")
        pdf = render_cv_bytes(CVContent.from_json(view.tailored_content_json))
        safe = "".join(ch for ch in (view.company or "job") if ch.isalnum() or ch in "-_")
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="CV_{safe or "job"}.pdf"'},
        )

    return api


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=settings.server_port)


if __name__ == "__main__":
    main()
