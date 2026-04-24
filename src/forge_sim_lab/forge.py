from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Callable

from .models import SimulationConfig, SimulationResult
from .parser import parse_winners

LineCallback = Callable[[str, str], None] | None


def _normalize_deck_args(config: SimulationConfig) -> list[str]:
    deck_args: list[str] = []
    deck_dir = config.deck_directory.resolve() if config.deck_directory else None

    for deck in config.decks:
        deck_path = Path(deck).expanduser()
        if config.format_name.lower() == "commander":
            deck_args.append(deck_path.name)
            continue
        if deck_dir is not None:
            try:
                resolved = deck_path.resolve()
                if resolved.parent == deck_dir:
                    deck_args.append(resolved.name)
                    continue
            except OSError:
                pass
            deck_args.append(deck_path.name)
        else:
            deck_args.append(str(deck_path))
    return deck_args


def _sibling_forge_script(forge_path: Path) -> Path | None:
    parent = forge_path.expanduser().resolve().parent
    candidates = [parent / "forge.sh", parent / "forge"]
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _launcher_prefix(config: SimulationConfig) -> list[str]:
    forge_path = config.forge_jar.expanduser()
    suffix = forge_path.suffix.lower()

    if forge_path.name in {"forge.sh", "forge"} and forge_path.exists():
        return [str(forge_path)]

    if config.prefer_forge_script:
        sibling = _sibling_forge_script(forge_path)
        if sibling is not None:
            return [str(sibling)]

    return [config.java_executable, "-jar", str(forge_path)]


def build_forge_command(config: SimulationConfig) -> list[str]:
    if len(config.decks) < 2:
        raise ValueError("At least two decks are required.")
    if len(config.decks) > 8:
        raise ValueError("Forge supports up to 8 players.")

    normalized_decks = _normalize_deck_args(config)
    command: list[str] = [*_launcher_prefix(config), "sim", "-d", *normalized_decks]

    if config.deck_directory and config.format_name.lower() != "commander":
        command.extend(["-D", str(config.deck_directory)])
    if config.game_count:
        command.extend(["-n", str(config.game_count)])
    if config.match_count:
        command.extend(["-m", str(config.match_count)])
    if config.format_name:
        command.extend(["-f", config.format_name])
    if config.tournament and config.player_count:
        command.extend(["-p", str(config.player_count)])
    if config.clock_seconds:
        command.extend(["-c", str(config.clock_seconds)])
    if config.quiet:
        command.append("-q")
    if config.tournament:
        command.append("-t")
    command.extend(config.extra_args)
    return command


def run_simulation(config: SimulationConfig) -> SimulationResult:
    command = build_forge_command(config)
    start = time.perf_counter()
    completed = subprocess.run(command, text=True, capture_output=True, timeout=config.timeout_seconds, check=False)
    duration_seconds = time.perf_counter() - start
    result = SimulationResult(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        winners=parse_winners(completed.stdout),
        duration_seconds=duration_seconds,
        config=config,
    )
    if config.output_directory:
        write_result_bundle(result, config.output_directory)
    return result


def run_simulation_streaming(config: SimulationConfig, line_callback: LineCallback = None) -> SimulationResult:
    command = build_forge_command(config)
    start = time.perf_counter()
    process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1)
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    try:
        assert process.stdout is not None
        for line in iter(process.stdout.readline, ""):
            stdout_lines.append(line)
            if line_callback:
                line_callback("stdout", line)
        process.stdout.close()
        assert process.stderr is not None
        for line in iter(process.stderr.readline, ""):
            stderr_lines.append(line)
            if line_callback:
                line_callback("stderr", line)
        process.stderr.close()
        return_code = process.wait(timeout=config.timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        return_code = -9
        stderr_lines.append(f"Timed out after {config.timeout_seconds} seconds\n")
        if line_callback:
            line_callback("stderr", stderr_lines[-1])
    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)
    duration_seconds = time.perf_counter() - start
    result = SimulationResult(
        command=command,
        return_code=return_code,
        stdout=stdout,
        stderr=stderr,
        winners=parse_winners(stdout),
        duration_seconds=duration_seconds,
        config=config,
    )
    if config.output_directory:
        write_result_bundle(result, config.output_directory)
    return result


def write_result_bundle(result: SimulationResult, output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "raw_stdout.txt").write_text(result.stdout, encoding="utf-8")
    (output_directory / "raw_stderr.txt").write_text(result.stderr, encoding="utf-8")
    (output_directory / "result.json").write_text(json.dumps(result.to_jsonable(), indent=2), encoding="utf-8")
