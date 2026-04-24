from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import SimulationConfig


@dataclass(slots=True)
class HookConfig:
    before_all: list[str] = field(default_factory=list)
    after_all: list[str] = field(default_factory=list)
    before_each: list[str] = field(default_factory=list)
    after_each: list[str] = field(default_factory=list)
    cwd: Path | None = None


@dataclass(slots=True)
class BatchPlan:
    name: str
    config: SimulationConfig
    repetitions: int = 1
    workers: int = 1
    stream_output: bool = False
    output_directory: Path | None = None
    hooks: HookConfig = field(default_factory=HookConfig)


@dataclass(slots=True)
class BatchConfigFile:
    defaults: dict[str, Any]
    plans: list[BatchPlan]


def _as_path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value)).expanduser()


def _as_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _make_sim_config(data: dict[str, Any]) -> SimulationConfig:
    return SimulationConfig(
        forge_jar=Path(str(data["forge_jar"])).expanduser(),
        decks=[str(item) for item in data["decks"]],
        deck_directory=_as_path(data.get("deck_directory")),
        game_count=int(data.get("game_count", 1) or 1),
        match_count=int(data["match_count"]) if data.get("match_count") not in (None, "") else None,
        format_name=str(data.get("format_name", "commander")),
        player_count=int(data["player_count"]) if data.get("player_count") not in (None, "") else None,
        tournament=bool(data.get("tournament", False)),
        quiet=bool(data.get("quiet", True)),
        timeout_seconds=int(data.get("timeout_seconds", 300) or 300),
        java_executable=str(data.get("java_executable", "java") or "java"),
        prefer_forge_script=bool(data.get("prefer_forge_script", True)),
        clock_seconds=int(data["clock_seconds"]) if data.get("clock_seconds") not in (None, "") else None,
        output_directory=_as_path(data.get("output_directory")),
        extra_args=_as_list(data.get("extra_args")),
    )


def load_batch_config(path: Path) -> BatchConfigFile:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = dict(payload.get("defaults") or {})
    raw_plans = payload.get("plans") or payload.get("runs") or []
    plans: list[BatchPlan] = []

    for index, raw_plan in enumerate(raw_plans, start=1):
        merged = dict(defaults)
        merged.update({k: v for k, v in raw_plan.items() if k not in {"hooks", "workers", "repetitions", "stream_output", "name"}})
        hooks_raw = dict(defaults.get("hooks") or {})
        hooks_raw.update(raw_plan.get("hooks") or {})
        hooks = HookConfig(
            before_all=_as_list(hooks_raw.get("before_all")),
            after_all=_as_list(hooks_raw.get("after_all")),
            before_each=_as_list(hooks_raw.get("before_each")),
            after_each=_as_list(hooks_raw.get("after_each")),
            cwd=_as_path(hooks_raw.get("cwd")),
        )
        config = _make_sim_config(merged)
        plan = BatchPlan(
            name=str(raw_plan.get("name") or f"plan_{index:02d}"),
            config=config,
            repetitions=int(raw_plan.get("repetitions", defaults.get("repetitions", 1)) or 1),
            workers=int(raw_plan.get("workers", defaults.get("workers", 1)) or 1),
            stream_output=bool(raw_plan.get("stream_output", defaults.get("stream_output", False))),
            output_directory=_as_path(raw_plan.get("output_directory", merged.get("output_directory"))),
            hooks=hooks,
        )
        plans.append(plan)

    return BatchConfigFile(defaults=defaults, plans=plans)
