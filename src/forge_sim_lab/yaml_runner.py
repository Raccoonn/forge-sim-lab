from __future__ import annotations

from pathlib import Path
from typing import Callable

from .batch_config import BatchPlan, load_batch_config
from .hooks import run_shell_hook
from .league import run_league_batch
from .models import LeagueSummary, ProgressEvent

ProgressCallback = Callable[[ProgressEvent], None] | None


def _emit(callback: ProgressCallback, kind: str, message: str, payload: dict | None = None) -> None:
    if callback:
        callback(ProgressEvent(kind=kind, message=message, payload=payload))


def _run_hook_group(commands: list[str], *, cwd: Path | None, env: dict[str, str], callback: ProgressCallback, label: str) -> None:
    for command in commands:
        _emit(callback, "hook_start", f"{label}: {command}", {"command": command})
        completed = run_shell_hook(command, cwd=cwd, env=env)
        if completed.stdout:
            _emit(callback, "hook_stdout", completed.stdout.rstrip("\n"), {"command": command})
        if completed.stderr:
            _emit(callback, "hook_stderr", completed.stderr.rstrip("\n"), {"command": command})
        if completed.returncode != 0:
            raise RuntimeError(f"Hook failed ({label}) rc={completed.returncode}: {command}")
        _emit(callback, "hook_complete", f"{label} complete: {command}", {"command": command})


def run_batch_plan(plan: BatchPlan, *, callback: ProgressCallback = None) -> LeagueSummary:
    config = plan.config
    if plan.output_directory is not None:
        config.output_directory = plan.output_directory
    if config.output_directory is None:
        raise ValueError(f"Plan {plan.name} must set output_directory either in defaults or plan.")
    config.output_directory.mkdir(parents=True, exist_ok=True)
    env = {
        "FORGE_SIM_PLAN_NAME": plan.name,
        "FORGE_SIM_OUTPUT_DIR": str(config.output_directory),
    }

    _run_hook_group(plan.hooks.before_all, cwd=plan.hooks.cwd, env=env, callback=callback, label=f"{plan.name} before_all")
    try:
        _, summary = run_league_batch(
            base_config=config,
            repetitions=plan.repetitions,
            root_output_directory=config.output_directory,
            progress_callback=callback,
            stream_output=plan.stream_output,
            worker_count=plan.workers,
            before_each_hooks=plan.hooks.before_each,
            after_each_hooks=plan.hooks.after_each,
            hook_cwd=plan.hooks.cwd,
            plan_name=plan.name,
        )
    finally:
        _run_hook_group(plan.hooks.after_all, cwd=plan.hooks.cwd, env=env, callback=callback, label=f"{plan.name} after_all")
    return summary


def run_yaml_config(path: Path, *, callback: ProgressCallback = None) -> dict[str, dict]:
    config_file = load_batch_config(path)
    summaries: dict[str, dict] = {}
    for plan in config_file.plans:
        _emit(callback, "plan_start", f"Starting plan: {plan.name}", {"plan": plan.name})
        summary = run_batch_plan(plan, callback=callback)
        summaries[plan.name] = summary.to_jsonable()
        _emit(callback, "plan_complete", f"Completed plan: {plan.name}", {"plan": plan.name, "summary": summary.to_jsonable()})
    return summaries
