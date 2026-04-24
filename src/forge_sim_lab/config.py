from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FORMATS = [
    "commander",
    "constructed",
    "standard",
    "modern",
    "legacy",
    "vintage",
    "pioneer",
    "brawl",
]

MAX_DECK_SLOTS = 12
FORGE_MAX_PLAYERS = 8
APP_DIR = Path.home() / ".config" / "forge-sim-lab"
SETTINGS_PATH = APP_DIR / "settings.json"


@dataclass(slots=True)
class AppDefaults:
    java_executable: str = "java"
    timeout_seconds: int = 300
    game_count: int = 1
    match_count: int | None = None
    repetitions: int = 1
    worker_count: int = 1
    format_name: str = "commander"
    quiet: bool = True
    tournament: bool = False
    base_output_directory: Path = Path.cwd() / "forge_sim_lab_runs"


def load_user_settings() -> dict[str, str]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_user_settings(settings: dict[str, str]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
