from __future__ import annotations

import argparse
import json
from pathlib import Path

from .forge import build_forge_command, run_simulation, run_simulation_streaming
from .league import run_league_batch
from .models import ProgressEvent, SimulationConfig
from .yaml_runner import run_yaml_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Run headless Forge simulations.')
    parser.add_argument('--config-file', type=Path, help='YAML batch config file. When supplied, standard single-run args are ignored except --print-command is unavailable.')
    parser.add_argument('--forge-jar', type=Path, help='Path to Forge launcher or jar')
    parser.add_argument('--deck', action='append', help='Deck name or file basename. Repeat for each deck.')
    parser.add_argument('--deck-dir', type=Path, default=None, help='Directory containing decks')
    parser.add_argument('--output-dir', type=Path, default=None, help='Output directory for results')
    parser.add_argument('--java', default='java', help='Java executable')
    parser.add_argument('--prefer-forge-script', action='store_true', default=True, help='Prefer sibling forge.sh/forge launcher when available')
    parser.add_argument('--no-prefer-forge-script', action='store_false', dest='prefer_forge_script', help='Force direct java -jar launch')
    parser.add_argument('--format', dest='format_name', default='commander', help='Forge format')
    parser.add_argument('--games', type=int, default=1, help='Games per sim')
    parser.add_argument('--matches', type=int, default=None, help='Matches per sim')
    parser.add_argument('--players', type=int, default=None, help='Player count')
    parser.add_argument('--workers', type=int, default=1, help='Parallel workers for non-streaming batch runs')
    parser.add_argument('--clock', type=int, default=None, help='Clock seconds')
    parser.add_argument('--timeout', type=int, default=300, help='Timeout seconds')
    parser.add_argument('--repetitions', type=int, default=1, help='How many repeated runs to execute')
    parser.add_argument('--tournament', action='store_true', help='Pass -t to Forge')
    parser.add_argument('--quiet', action='store_true', help='Pass -q to Forge')
    parser.add_argument('--stream', action='store_true', help='Stream stdout/stderr while process runs')
    parser.add_argument('--print-command', action='store_true', help='Print full Forge command before running')
    parser.add_argument('--extra-arg', action='append', default=[], help='Extra raw Forge arg, repeat as needed')
    return parser


def _progress_printer(event: ProgressEvent, *, stream_lines: bool) -> None:
    if event.kind == 'line':
        if stream_lines:
            stream_name = (event.payload or {}).get('stream', 'stdout').upper()
            print(f'[{stream_name}] {event.message}')
        return
    if event.kind in {'hook_stdout', 'hook_stderr'}:
        prefix = 'HOOK STDERR' if event.kind == 'hook_stderr' else 'HOOK STDOUT'
        print(f'[{prefix}] {event.message}')
        return
    print(f'[{event.kind}] {event.message}')


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.config_file:
        summaries = run_yaml_config(args.config_file, callback=lambda e: _progress_printer(e, stream_lines=True))
        print(json.dumps(summaries, indent=2))
        return 0

    if not args.forge_jar or not args.deck:
        parser.error('--forge-jar and at least two --deck arguments are required unless --config-file is used.')

    config = SimulationConfig(
        forge_jar=args.forge_jar,
        decks=args.deck,
        deck_directory=args.deck_dir,
        game_count=args.games,
        match_count=args.matches,
        format_name=args.format_name,
        player_count=args.players,
        tournament=args.tournament,
        quiet=args.quiet,
        prefer_forge_script=args.prefer_forge_script,
        timeout_seconds=args.timeout,
        java_executable=args.java,
        clock_seconds=args.clock,
        output_directory=args.output_dir,
        extra_args=args.extra_arg,
    )

    if args.print_command:
        print('COMMAND:', ' '.join(build_forge_command(config)))

    if args.repetitions <= 1:
        if args.stream:
            def _callback(stream_name: str, line: str) -> None:
                prefix = 'STDERR' if stream_name == 'stderr' else 'STDOUT'
                print(f'[{prefix}] {line}', end='')
            result = run_simulation_streaming(config, line_callback=_callback)
        else:
            result = run_simulation(config)
        print(json.dumps(result.to_jsonable(), indent=2))
        return 0 if result.return_code == 0 else result.return_code

    output_dir = args.output_dir or (Path.cwd() / 'forge_sim_lab_batch')
    _, summary = run_league_batch(
        base_config=config,
        repetitions=args.repetitions,
        root_output_directory=output_dir,
        progress_callback=lambda e: _progress_printer(e, stream_lines=args.stream),
        stream_output=args.stream,
        worker_count=args.workers,
    )
    print(json.dumps(summary.to_jsonable(), indent=2))
    return 0
