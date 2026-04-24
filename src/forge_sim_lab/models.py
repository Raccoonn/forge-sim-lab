from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SimulationConfig:
    forge_jar: Path
    decks: list[str]
    deck_directory: Path | None = None
    game_count: int = 1
    match_count: int | None = None
    format_name: str = "commander"
    player_count: int | None = None
    tournament: bool = False
    quiet: bool = True
    timeout_seconds: int = 300
    java_executable: str = "java"
    prefer_forge_script: bool = True
    clock_seconds: int | None = None
    output_directory: Path | None = None
    extra_args: list[str] = field(default_factory=list)

    def to_jsonable(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["forge_jar"] = str(self.forge_jar)
        payload["deck_directory"] = str(self.deck_directory) if self.deck_directory else None
        payload["output_directory"] = str(self.output_directory) if self.output_directory else None
        return payload


@dataclass(slots=True)
class SimulationResult:
    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    winners: list[str]
    duration_seconds: float
    config: SimulationConfig

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "winners": self.winners,
            "duration_seconds": self.duration_seconds,
            "config": self.config.to_jsonable(),
        }


@dataclass(slots=True)
class LeagueSummary:
    total_runs: int
    successful_runs: int
    failed_runs: int
    winner_counts: dict[str, int]
    return_codes: dict[str, int]
    run_directories: list[str]
    worker_count: int = 1
    mode: str = "sequential"

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "winner_counts": self.winner_counts,
            "return_codes": self.return_codes,
            "run_directories": self.run_directories,
            "worker_count": self.worker_count,
            "mode": self.mode,
        }


@dataclass(slots=True)
class ProgressEvent:
    kind: str
    message: str = ""
    current: int | None = None
    total: int | None = None
    payload: dict[str, Any] | None = None
