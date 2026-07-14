"""Application settings, loaded from environment / .env.

Centralizing config here keeps secrets and environment-specific paths out of the
code, and makes the v1 (SQLite, local) -> v2 (Postgres, deployed) switch a matter of
changing environment values, not code.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root (…/JobFinder), derived from this file's location: src/jobfinder/config.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JOBFINDER_",
        extra="ignore",
    )

    database_url: str = Field(default="sqlite:///./data/jobfinder.db")
    generated_dir: Path = Field(default=PROJECT_ROOT / "generated")

    # LLM model used for CV tailoring (build step 4). Override with
    # JOBFINDER_ANTHROPIC_MODEL (e.g. claude-opus-4-8 for higher quality).
    anthropic_model: str = Field(default="claude-sonnet-5")

    # Port for the local HTTP API (browser-extension backend). The extension's
    # manifest must be allowed to reach this port, so change both together.
    server_port: int = Field(default=8765)

    def cv_path(self) -> Path:
        """The user's master CV JSON, falling back to the committed example."""
        master = PROJECT_ROOT / "cv" / "master_cv.json"
        return master if master.exists() else PROJECT_ROOT / "cv" / "example_cv.json"

    # Read without the JOBFINDER_ prefix to match each vendor's conventional name.
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    adzuna_app_id: str | None = Field(default=None, alias="ADZUNA_APP_ID")
    adzuna_app_key: str | None = Field(default=None, alias="ADZUNA_APP_KEY")

    def ensure_dirs(self) -> None:
        """Create local directories the app writes to (data dir, generated output)."""
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
