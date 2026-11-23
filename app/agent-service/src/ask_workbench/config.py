from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import SettingsConfigDict

from ag_workbench.config import WorkbenchSettings

# app/agent-service/src/ask_workbench/config.py -> parents[4] is ask-ask-something root
AGENT_SERVICE_DIR = Path(__file__).resolve().parents[2]
APP_DIR = AGENT_SERVICE_DIR.parent
REPO_ROOT = APP_DIR.parent
SKILLS_ROOT = REPO_ROOT / "skills"
SKILL_SCRIPTS_DIR = SKILLS_ROOT / "ask-ask-something" / "scripts"


class Settings(WorkbenchSettings):
    model_config = SettingsConfigDict(
        env_file=str(AGENT_SERVICE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    agent_service_port: int = 8000
    data_dir: Path = AGENT_SERVICE_DIR / ".data"


def get_settings() -> Settings:
    data_override = os.environ.get("ASK_WORKBENCH_DATA_DIR")
    if data_override:
        return Settings(data_dir=Path(data_override))
    return Settings()
