from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/agent-service/src/ask_workbench/config.py -> parents[4] is ask-ask-something root
AGENT_SERVICE_DIR = Path(__file__).resolve().parents[2]
APP_DIR = AGENT_SERVICE_DIR.parent
REPO_ROOT = APP_DIR.parent
SKILLS_ROOT = REPO_ROOT / "skills"
SKILL_SCRIPTS_DIR = SKILLS_ROOT / "ask-ask-something" / "scripts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(AGENT_SERVICE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vertex_project_id: str = ""
    vertex_location: str = "global"
    agent_model: str = ""
    agent_service_port: int = 8000
    default_workspaces_json: str = ""
    data_dir: Path = AGENT_SERVICE_DIR / ".data"

    @property
    def resolved_vertex_project_id(self) -> str | None:
        val = (
            self.vertex_project_id.strip()
            or os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        )
        return val or None

    @property
    def sessions_dir(self) -> Path:
        p = self.data_dir / "sessions"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def conversations_file(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "conversations.json"

    @property
    def workspaces_file(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "workspaces.json"


def get_settings() -> Settings:
    data_override = os.environ.get("ASK_WORKBENCH_DATA_DIR")
    if data_override:
        return Settings(data_dir=Path(data_override))
    return Settings()
