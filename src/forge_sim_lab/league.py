from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Callable

from .forge import run_simulation, run_simulation_streaming
from .hooks import run_shell_hook
from .models import LeagueSummary, ProgressEvent, SimulationConfig, SimulationResult

ProgressCallback = Callable[[ProgressEvent], None] | None


def _run_single_job(index: int, base_config: SimulationConfig, run_dir: Path) -> SimulationResult:
    config = deepcopy(base_config)
    config.output_directory = run_dir
    return run_simulation(config)


def _run_hook_list(
    commands: list[str], *, cwd: Path | None, env: dict[str, str], progress_callback: ProgressCallback, label: str
) -> None:
    for command in commands:
        if progress_callback:
            progress_callback(ProgressEvent(kind="hook_start", message=f"{label}: {command}", payload={"command": command}))
        completed = run_shell_hook(command, cwd=cwd, env=env)
        if completed.stdout and progress_callback:
            progress_callback(
                ProgressEvent(kind="hook_stdout", message=completed.stdout.rstrip("\n"), payload={"command": command})
            )
        if completed.stderr and progress_callback:
            progress_callback(
                ProgressEvent(kind="hook_stderr", message=completed.stderr.rstrip("\n"), payload={"command": command})
            )
        if completed.returncode != 0:
            raise RuntimeError(f"Hook failed ({label}) rc={completed.returncode}: {command}")
        if progress_callback:
            progress_callback(
                ProgressEvent(kind="hook_complete", message=f"{label} complete: {command}", payload={"command": command})
            )


def run_league_batch(
    base_config: SimulationConfig,
    repetitions: int,
    root_output_directory: Path,
    progress_callback: ProgressCallback = None,
    stream_output: bool = False,
    worker_count: int = 1,
    before_each_hooks: list[str] | None = None,
    after_each_hooks: list[str] | None = None,
    hook_cwd: Path | None = None,
    plan_name: str | None = None,
) -> tuple[list[SimulationResult], LeagueSummary]:
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if worker_count < 1:
        raise ValueError("worker_count must be at least 1")

    before_each_hooks = before_each_hooks or []
    after_each_hooks = after_each_hooks or []
    root_output_directory.mkdir(parents=True, exist_ok=True)

    results: list[SimulationResult] = []
    winner_counts: Counter[str] = Counter()
    return_codes: Counter[str] = Counter()
    run_directories: list[str] = []
    jsonl_path = root_output_directory / "results.jsonl"
    mode = "parallel" if worker_count > 1 and not stream_output and not before_each_hooks and not after_each_hooks else "sequential"

    run_dirs = [root_output_directory / f"run_{index:04d}" for index in range(1, repetitions + 1)]

    with jsonl_path.open("w", encoding="utf-8") as handle:
        if mode == "parallel":
            if progress_callback:
                progress_callback(
                    ProgressEvent(
                        kind="parallel_start",
                        message=f"Starting parallel batch with {worker_count} workers",
                        current=0,
                        total=repetitions,
                        payload={"workers": worker_count},
                    )
                )
            with ProcessPoolExecutor(max_workers=worker_count) as executor:
                future_map = {
                    executor.submit(_run_single_job, index, base_config, run_dirs[index - 1]): index
                    for index in range(1, repetitions + 1)
                }
                for future in as_completed(future_map):
                    index = future_map[future]
                    result = future.result()
                    results.append(result)
                    run_directories.append(str(run_dirs[index - 1]))
                    return_codes[str(result.return_code)] += 1
                    for winner in result.winners:
                        winner_counts[winner] += 1
                    handle.write(json.dumps(result.to_jsonable()) + "\n")
                    handle.flush()
                    if progress_callback:
                        winners_text = ", ".join(result.winners) if result.winners else "unknown"
                        progress_callback(
                            ProgressEvent(
                                kind="run_complete",
                                message=f"Completed run {index}/{repetitions} | rc={result.return_code} | winners={winners_text}",
                                current=len(results),
                                total=repetitions,
                                payload={"return_code": result.return_code, "winners": result.winners, "run_index": index},
                            )
                        )
        else:
            if stream_output and worker_count > 1 and progress_callback:
                progress_callback(
                    ProgressEvent(
                        kind="note",
                        message="Streaming output forces sequential mode. Multiprocessing is only used for non-streaming batches.",
                        payload={"workers": worker_count},
                    )
                )
            if (before_each_hooks or after_each_hooks) and worker_count > 1 and progress_callback:
                progress_callback(
                    ProgressEvent(
                        kind="note",
                        message="Per-run shell hooks force sequential mode.",
                        payload={"workers": worker_count},
                    )
                )
            for index in range(1, repetitions + 1):
                if progress_callback:
                    progress_callback(
                        ProgressEvent(kind="run_start", message=f"Starting run {index}/{repetitions}", current=index - 1, total=repetitions)
                    )
                config = deepcopy(base_config)
                run_dir = run_dirs[index - 1]
                config.output_directory = run_dir
                env = {
                    "FORGE_SIM_RUN_INDEX": str(index),
                    "FORGE_SIM_TOTAL_RUNS": str(repetitions),
                    "FORGE_SIM_RUN_DIR": str(run_dir),
                    "FORGE_SIM_PLAN_NAME": plan_name or "",
                }
                _run_hook_list(before_each_hooks, cwd=hook_cwd, env=env, progress_callback=progress_callback, label=f"before_each run {index}")
                if stream_output:
                    def _line_callback(stream_name: str, line: str) -> None:
                        if progress_callback:
                            progress_callback(
                                ProgressEvent(
                                    kind="line",
                                    message=line.rstrip("\n"),
                                    current=index - 1,
                                    total=repetitions,
                                    payload={"stream": stream_name, "run_index": index},
                                )
                            )
                    result = run_simulation_streaming(config, line_callback=_line_callback)
                else:
                    result = run_simulation(config)
                _run_hook_list(after_each_hooks, cwd=hook_cwd, env=env, progress_callback=progress_callback, label=f"after_each run {index}")
                results.append(result)
                run_directories.append(str(run_dir))
                return_codes[str(result.return_code)] += 1
                for winner in result.winners:
                    winner_counts[winner] += 1
                handle.write(json.dumps(result.to_jsonable()) + "\n")
                handle.flush()
                if progress_callback:
                    winners_text = ", ".join(result.winners) if result.winners else "unknown"
                    progress_callback(
                        ProgressEvent(
                            kind="run_complete",
                            message=f"Completed run {index}/{repetitions} | rc={result.return_code} | winners={winners_text}",
                            current=index,
                            total=repetitions,
                            payload={"return_code": result.return_code, "winners": result.winners, "run_index": index},
                        )
                    )

    results.sort(key=lambda item: str(item.config.output_directory or ""))
    run_directories.sort()

    summary = LeagueSummary(
        total_runs=repetitions,
        successful_runs=sum(1 for item in results if item.return_code == 0),
        failed_runs=sum(1 for item in results if item.return_code != 0),
        winner_counts=dict(winner_counts),
        return_codes=dict(return_codes),
        run_directories=run_directories,
        worker_count=worker_count,
        mode=mode,
    )

    (root_output_directory / "summary.json").write_text(json.dumps(summary.to_jsonable(), indent=2), encoding="utf-8")
    if progress_callback:
        progress_callback(
            ProgressEvent(kind="batch_complete", message="Batch complete", current=repetitions, total=repetitions, payload=summary.to_jsonable())
        )
    return results, summary
