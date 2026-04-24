from __future__ import annotations
import json
import queue
import threading
import traceback
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from .config import (
    AppDefaults,
    DEFAULT_FORMATS,
    FORGE_MAX_PLAYERS,
    MAX_DECK_SLOTS,
    load_user_settings,
    save_user_settings,
)

COMMANDER_DECK_DIR = Path.home() / ".forge" / "decks" / "commander"
from .forge import build_forge_command, run_simulation_streaming
from .league import run_league_batch
from .models import ProgressEvent, SimulationConfig, SimulationResult
from .yaml_runner import run_yaml_config
APP_DEFAULTS = AppDefaults()

def _normalize_log_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "")
    return text

class LiveLogWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.window = tk.Toplevel(root)
        self.window.title("Forge Sim Lab Live Output")
        self.window.geometry("1100x700")
        top = ttk.Frame(self.window, padding=8)
        top.pack(fill="x")
        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(top, textvariable=self.status_var).pack(side="left")
        self.progress = ttk.Progressbar(top, mode="determinate", maximum=100)
        self.progress.pack(side="right", fill="x", expand=True, padx=(10, 0))
        text_frame = ttk.Frame(self.window, padding=(8, 0, 8, 8))
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(
            text_frame,
            wrap="none",
            background="#050505",
            foreground="#37ff37",
            insertbackground="#37ff37",
        )
        self.text.pack(side="left", fill="both", expand=True)
        yscroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        yscroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=yscroll.set)
        xscroll = ttk.Scrollbar(self.window, orient="horizontal", command=self.text.xview)
        xscroll.pack(fill="x", padx=8, pady=(0, 8))
        self.text.configure(xscrollcommand=xscroll.set)
        button_row = ttk.Frame(self.window, padding=(8, 0, 8, 8))
        button_row.pack(fill="x")
        ttk.Button(button_row, text="Clear", command=self.clear).pack(side="left")
        ttk.Button(button_row, text="Close", command=self.window.withdraw).pack(side="right")
    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
    def clear(self) -> None:
        self.text.delete("1.0", "end")
    def append(self, text: str) -> None:
        normalized = _normalize_log_text(text)
        if not normalized:
            return
        self.text.insert("end", normalized)
        self.text.see("end")
    def set_status(self, text: str) -> None:
        self.status_var.set(text)
    def set_progress(self, current: int, total: int) -> None:
        if total <= 0:
            self.progress.configure(value=0, maximum=100)
            return
        self.progress.configure(maximum=total, value=current)
class ForgeSimLabApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Forge Sim Lab")
        self.root.geometry("1280x920")
        self.message_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.live_log_window = LiveLogWindow(root)
        self.live_log_window.window.withdraw()
        self.saved_settings = load_user_settings()
        self.jar_var = tk.StringVar(value=self.saved_settings.get("forge_jar", ""))
        self.prefer_script_var = tk.BooleanVar(value=bool(self.saved_settings.get("prefer_forge_script", True)))
        self.deck_dir_var = tk.StringVar(value=self.saved_settings.get("deck_directory", ""))
        self.output_dir_var = tk.StringVar(value=self.saved_settings.get("output_directory", str(APP_DEFAULTS.base_output_directory)))
        self.java_var = tk.StringVar(value=self.saved_settings.get("java_executable", APP_DEFAULTS.java_executable))
        self.format_var = tk.StringVar(value=self.saved_settings.get("format_name", APP_DEFAULTS.format_name))
        self.games_var = tk.StringVar(value=str(self.saved_settings.get("game_count", APP_DEFAULTS.game_count)))
        self.matches_var = tk.StringVar(value=str(self.saved_settings.get("match_count", "")))
        self.player_count_var = tk.StringVar(value=str(self.saved_settings.get("player_count", "")))
        self.timeout_var = tk.StringVar(value=str(self.saved_settings.get("timeout_seconds", APP_DEFAULTS.timeout_seconds)))
        self.repetitions_var = tk.StringVar(value=str(self.saved_settings.get("repetitions", APP_DEFAULTS.repetitions)))
        self.workers_var = tk.StringVar(value=str(self.saved_settings.get("worker_count", APP_DEFAULTS.worker_count)))
        self.clock_var = tk.StringVar(value=str(self.saved_settings.get("clock_seconds", "")))
        self.quiet_var = tk.BooleanVar(value=bool(self.saved_settings.get("quiet", APP_DEFAULTS.quiet)))
        self.tournament_var = tk.BooleanVar(value=bool(self.saved_settings.get("tournament", APP_DEFAULTS.tournament)))
        self.stream_output_var = tk.BooleanVar(value=bool(self.saved_settings.get("stream_output", True)))
        self.auto_open_live_log_var = tk.BooleanVar(value=bool(self.saved_settings.get("auto_open_live_log", True)))
        self.extra_args_var = tk.StringVar(value=self.saved_settings.get("extra_args", ""))
        self.deck_vars: list[tk.StringVar] = [tk.StringVar() for _ in range(MAX_DECK_SLOTS)]
        self._build_ui()
        self._poll_queue()
    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        top = ttk.LabelFrame(outer, text="Forge / Java / Output", padding=10)
        top.pack(fill="x", pady=(0, 10))
        self._path_row(top, 0, "Forge JAR", self.jar_var, self._browse_jar)
        self._path_row(top, 1, "Deck Directory", self.deck_dir_var, self._browse_deck_dir)
        self._path_row(top, 2, "Output Directory", self.output_dir_var, self._browse_output_dir)
        ttk.Label(top, text="Java").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(top, textvariable=self.java_var, width=40).grid(row=3, column=1, sticky="ew", pady=4)
        top.columnconfigure(1, weight=1)
        settings = ttk.LabelFrame(outer, text="Simulation Settings", padding=10)
        settings.pack(fill="x", pady=(0, 10))
        format_combo = ttk.Combobox(settings, textvariable=self.format_var, values=DEFAULT_FORMATS, width=16)
        format_combo["state"] = "normal"
        entries = [
            ("Format", format_combo),
            ("Games", ttk.Entry(settings, textvariable=self.games_var, width=12)),
            ("Matches", ttk.Entry(settings, textvariable=self.matches_var, width=12)),
            ("Player Count", ttk.Entry(settings, textvariable=self.player_count_var, width=12)),
            ("Clock (sec)", ttk.Entry(settings, textvariable=self.clock_var, width=12)),
            ("Timeout (sec)", ttk.Entry(settings, textvariable=self.timeout_var, width=12)),
            ("Batch Repetitions", ttk.Entry(settings, textvariable=self.repetitions_var, width=12)),
            ("Workers", ttk.Entry(settings, textvariable=self.workers_var, width=12)),
        ]
        for column, (label, widget) in enumerate(entries):
            ttk.Label(settings, text=label).grid(row=0, column=column * 2, sticky="w", padx=(0, 6), pady=4)
            widget.grid(row=0, column=column * 2 + 1, sticky="w", padx=(0, 12), pady=4)
        ttk.Checkbutton(settings, text="Quiet (-q)", variable=self.quiet_var).grid(row=1, column=0, sticky="w", pady=6)
        ttk.Checkbutton(settings, text="Tournament (-t)", variable=self.tournament_var).grid(row=1, column=1, sticky="w", pady=6)
        ttk.Checkbutton(settings, text="Prefer forge.sh launcher", variable=self.prefer_script_var).grid(row=1, column=2, sticky="w", pady=6)
        ttk.Checkbutton(settings, text="Stream output live", variable=self.stream_output_var).grid(row=1, column=3, sticky="w", pady=6)
        ttk.Checkbutton(settings, text="Auto-open live log", variable=self.auto_open_live_log_var).grid(row=1, column=4, sticky="w", pady=6)
        ttk.Label(settings, text="Extra Args").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=self.extra_args_var, width=120).grid(
            row=2,
            column=1,
            columnspan=10,
            sticky="ew",
            pady=4,
        )
        note = ttk.Label(
            settings,
            text=(
                f"Forge supports up to {FORGE_MAX_PLAYERS} players. Commander sims resolve deck names from "
                f"{COMMANDER_DECK_DIR}. On Linux, GUI runs prefer a sibling forge.sh launcher when available."
            ),
        )
        note.grid(row=3, column=0, columnspan=12, sticky="w", pady=(4, 0))
        decks = ttk.LabelFrame(outer, text="Deck Inputs (2 to 12)", padding=10)
        decks.pack(fill="x", pady=(0, 10))
        for index, deck_var in enumerate(self.deck_vars):
            row = index // 2
            pair_offset = (index % 2) * 3
            ttk.Label(decks, text=f"Deck {index + 1}").grid(row=row, column=pair_offset, sticky="w", padx=(0, 6), pady=4)
            ttk.Entry(decks, textvariable=deck_var, width=46).grid(row=row, column=pair_offset + 1, sticky="ew", pady=4)
            ttk.Button(
                decks,
                text="Browse",
                command=lambda var=deck_var: self._browse_deck_file(var),
            ).grid(row=row, column=pair_offset + 2, padx=(6, 14), pady=4)
        for col in range(6):
            decks.columnconfigure(col, weight=1)
        action_row = ttk.Frame(outer)
        action_row.pack(fill="x", pady=(0, 10))
        ttk.Button(action_row, text="Open Live Log Window", command=self._open_live_log).pack(side="left")
        ttk.Button(action_row, text="Run Single Simulation", command=self._run_single).pack(side="left", padx=(10, 0))
        ttk.Button(action_row, text="Run Batch / League", command=self._run_batch).pack(side="left", padx=(10, 0))
        ttk.Button(action_row, text="Preview Command", command=self._preview_command).pack(side="left", padx=(10, 0))
        ttk.Button(action_row, text="Run YAML Config", command=self._run_yaml_config).pack(side="left", padx=(10, 0))
        status_frame = ttk.LabelFrame(outer, text="Status / Results", padding=10)
        status_frame.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(status_frame, textvariable=self.status_var).pack(anchor="w")
        self.progress = ttk.Progressbar(status_frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(8, 8))
        output_container = ttk.Frame(status_frame)
        output_container.pack(fill="both", expand=True)
        self.output_text = tk.Text(output_container, wrap="word", height=18)
        self.output_text.pack(side="left", fill="both", expand=True)
        output_scroll = ttk.Scrollbar(output_container, orient="vertical", command=self.output_text.yview)
        output_scroll.pack(side="right", fill="y")
        self.output_text.configure(yscrollcommand=output_scroll.set)
    def _save_settings(self) -> None:
        settings = {
            "forge_jar": self.jar_var.get().strip(),
            "deck_directory": self.deck_dir_var.get().strip(),
            "output_directory": self.output_dir_var.get().strip(),
            "java_executable": self.java_var.get().strip() or "java",
            "format_name": self.format_var.get().strip(),
            "game_count": self.games_var.get().strip() or "1",
            "match_count": self.matches_var.get().strip(),
            "player_count": self.player_count_var.get().strip(),
            "timeout_seconds": self.timeout_var.get().strip() or "300",
            "repetitions": self.repetitions_var.get().strip() or "1",
            "clock_seconds": self.clock_var.get().strip(),
            "quiet": self.quiet_var.get(),
            "prefer_forge_script": self.prefer_script_var.get(),
            "tournament": self.tournament_var.get(),
            "stream_output": self.stream_output_var.get(),
            "auto_open_live_log": self.auto_open_live_log_var.get(),
            "extra_args": self.extra_args_var.get().strip(),
            "worker_count": self.workers_var.get().strip() or "1",
        }
        save_user_settings(settings)
    def _path_row(self, parent: ttk.Widget, row: int, label: str, variable: tk.StringVar, browse_callback) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="Browse", command=browse_callback).grid(row=row, column=2, padx=(8, 0), pady=4)
        parent.columnconfigure(1, weight=1)
    def _browse_jar(self) -> None:
        initial_dir = str(Path(self.jar_var.get()).parent) if self.jar_var.get().strip() else None
        path = filedialog.askopenfilename(title="Select Forge launcher or JAR", initialdir=initial_dir, filetypes=[("Launchers and JAR", "forge.sh forge *.jar"), ("Shell scripts", "*.sh"), ("JAR files", "*.jar"), ("All files", "*.*")])
        if path:
            self.jar_var.set(path)
            self._save_settings()
    def _browse_deck_dir(self) -> None:
        initial_dir = self.deck_dir_var.get().strip()
        if not initial_dir and self.format_var.get().strip().lower() == "commander":
            initial_dir = str(COMMANDER_DECK_DIR)
        path = filedialog.askdirectory(title="Select deck directory", initialdir=initial_dir or None)
        if path:
            self.deck_dir_var.set(path)
            self._save_settings()
    def _browse_output_dir(self) -> None:
        initial_dir = self.output_dir_var.get().strip() or None
        path = filedialog.askdirectory(title="Select output directory", initialdir=initial_dir)
        if path:
            self.output_dir_var.set(path)
            self._save_settings()
    def _browse_deck_file(self, variable: tk.StringVar) -> None:
        initial_dir = self.deck_dir_var.get().strip()
        if not initial_dir and self.format_var.get().strip().lower() == "commander":
            initial_dir = str(COMMANDER_DECK_DIR)
        path = filedialog.askopenfilename(title="Select deck file", initialdir=initial_dir or None, filetypes=[("Deck files", "*.dck"), ("All files", "*.*")])
        if path:
            variable.set(path)
    def _open_live_log(self) -> None:
        self.live_log_window.show()
    def _append_output(self, text: str) -> None:
        normalized = _normalize_log_text(text)
        if not normalized:
            return
        self.output_text.insert("end", normalized)
        self.output_text.see("end")
    def _set_progress(self, current: int, total: int) -> None:
        if total <= 0:
            self.progress.configure(maximum=100, value=0)
            self.live_log_window.set_progress(0, 100)
            return
        self.progress.configure(maximum=total, value=current)
        self.live_log_window.set_progress(current, total)
    def _preview_command(self) -> None:
        try:
            config = self._collect_config()
            command = build_forge_command(config)
        except Exception as exc:
            messagebox.showerror("Invalid Configuration", str(exc))
            return
        self.output_text.delete("1.0", "end")
        self._append_output(" ".join(command) + "\n")
        self.status_var.set("Command preview generated.")
        self.live_log_window.set_status("Command preview generated.")
    def _collect_config(self) -> SimulationConfig:
        decks = [item.get().strip() for item in self.deck_vars if item.get().strip()]
        if len(decks) < 2:
            raise ValueError("Select or enter at least two decks.")
        if len(decks) > FORGE_MAX_PLAYERS:
            raise ValueError(f"Forge supports up to {FORGE_MAX_PLAYERS} players. Reduce the deck count.")
        output_dir_text = self.output_dir_var.get().strip()
        output_dir = Path(output_dir_text) if output_dir_text else None
        extra_args = [item for item in self.extra_args_var.get().split() if item]
        matches_text = self.matches_var.get().strip()
        players_text = self.player_count_var.get().strip()
        clock_text = self.clock_var.get().strip()
        deck_dir_value = self.deck_dir_var.get().strip()
        deck_directory = Path(deck_dir_value) if deck_dir_value else None
        config = SimulationConfig(
            forge_jar=Path(self.jar_var.get().strip()),
            decks=decks,
            deck_directory=deck_directory,
            game_count=int(self.games_var.get().strip() or "1"),
            match_count=int(matches_text) if matches_text else None,
            format_name=self.format_var.get().strip(),
            player_count=int(players_text) if players_text else None,
            tournament=self.tournament_var.get(),
            quiet=self.quiet_var.get(),
            prefer_forge_script=self.prefer_script_var.get(),
            timeout_seconds=int(self.timeout_var.get().strip() or "300"),
            java_executable=self.java_var.get().strip() or "java",
            clock_seconds=int(clock_text) if clock_text else None,
            output_directory=output_dir,
            extra_args=extra_args,
        )
        if config.format_name.lower() == "commander":
            commander_dir = COMMANDER_DECK_DIR.resolve()
            selected = [Path(deck).expanduser() for deck in decks]
            outside = []
            for deck_path in selected:
                try:
                    if deck_path.is_absolute() and deck_path.resolve().parent != commander_dir:
                        outside.append(deck_path.name)
                except OSError:
                    continue
            if outside:
                self._append_output(
                    "WARNING: Commander sims resolve deck names from ~/.forge/decks/commander. "
                    f"These selected files appear to live elsewhere: {', '.join(outside)}\n"
                )
        self._save_settings()
        return config
    def _run_single(self) -> None:
        self._launch_worker(mode="single")
    def _run_batch(self) -> None:
        self._launch_worker(mode="batch")
    def _launch_worker(self, mode: str) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("Already Running", "A simulation is already in progress.")
            return
        try:
            config = self._collect_config()
            repetitions = int(self.repetitions_var.get().strip() or "1")
            workers = int(self.workers_var.get().strip() or "1")
        except Exception as exc:
            messagebox.showerror("Invalid Configuration", str(exc))
            return
        self.output_text.delete("1.0", "end")
        self.status_var.set(f"Starting {mode} run...")
        self._append_output(f"Workers: {workers}\n")
        self._set_progress(0, repetitions if mode == "batch" else 1)
        self.live_log_window.clear()
        self.live_log_window.set_status(f"Starting {mode} run...")
        if self.auto_open_live_log_var.get():
            self._open_live_log()
        self.worker_thread = threading.Thread(
            target=self._worker_main,
            args=(mode, deepcopy(config), repetitions, workers),
            daemon=True,
        )
        self.worker_thread.start()
    def _worker_main(self, mode: str, config: SimulationConfig, repetitions: int, workers: int) -> None:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if config.output_directory is None:
                config.output_directory = APP_DEFAULTS.base_output_directory / f"run_{timestamp}"
            if mode == "single":
                config.output_directory.mkdir(parents=True, exist_ok=True)
                def _line_callback(stream_name: str, line: str) -> None:
                    self.message_queue.put(("progress_event", ProgressEvent(
                        kind="line",
                        message=line,
                        current=0,
                        total=1,
                        payload={"stream": stream_name},
                    )))
                result = run_simulation_streaming(
                    config,
                    line_callback=_line_callback if self.stream_output_var.get() else None,
                )
                self.message_queue.put(("single_complete", result))
            else:
                batch_root = config.output_directory
                batch_root.mkdir(parents=True, exist_ok=True)
                def _progress(event: ProgressEvent) -> None:
                    self.message_queue.put(("progress_event", event))
                _, summary = run_league_batch(
                    base_config=config,
                    repetitions=repetitions,
                    root_output_directory=batch_root,
                    progress_callback=_progress,
                    stream_output=self.stream_output_var.get(),
                    worker_count=workers,
                )
                self.message_queue.put(("batch_complete", summary))
        except Exception:
            self.message_queue.put(("error", traceback.format_exc()))
    def _run_yaml_config(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("Already Running", "A simulation is already in progress.")
            return
        path = filedialog.askopenfilename(title="Select YAML config", filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")])
        if not path:
            return
        self.output_text.delete("1.0", "end")
        self.status_var.set("Starting YAML config...")
        self.live_log_window.clear()
        if self.auto_open_live_log_var.get():
            self._open_live_log()
        self.worker_thread = threading.Thread(target=self._worker_yaml_main, args=(Path(path),), daemon=True)
        self.worker_thread.start()

    def _worker_yaml_main(self, path: Path) -> None:
        try:
            def _progress(event: ProgressEvent) -> None:
                self.message_queue.put(("progress_event", event))
            summaries = run_yaml_config(path, callback=_progress)
            self.message_queue.put(("yaml_complete", summaries))
        except Exception:
            self.message_queue.put(("error", traceback.format_exc()))

    def _poll_queue(self) -> None:
        try:
            while True:
                event_type, payload = self.message_queue.get_nowait()
                if event_type == "progress_event":
                    self._handle_progress_event(payload)
                elif event_type == "single_complete":
                    self._handle_single_complete(payload)
                elif event_type == "batch_complete":
                    self._handle_batch_complete(payload)
                elif event_type == "yaml_complete":
                    self._handle_yaml_complete(payload)
                elif event_type == "error":
                    self._handle_error(payload)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)
    def _handle_progress_event(self, event: ProgressEvent) -> None:
        if event.kind == "line":
            stream_name = (event.payload or {}).get("stream", "stdout")
            prefix = "[stderr] " if stream_name == "stderr" else ""
            self.live_log_window.append(prefix + event.message)
            if not self.stream_output_var.get():
                return
            self._append_output(prefix + event.message)
            return

        self.status_var.set(event.message)
        self.live_log_window.set_status(event.message)
        current = event.current or 0
        total = event.total or 1
        self._set_progress(current, total)
        line = f"{event.message}\n"
        self._append_output(line)
        self.live_log_window.append(line)

    def _handle_single_complete(self, result: SimulationResult) -> None:
        self.status_var.set(f"Single run complete. Return code: {result.return_code}")
        self.live_log_window.set_status(f"Single run complete. Return code: {result.return_code}")
        self._set_progress(1, 1)
        summary = {
            "return_code": result.return_code,
            "duration_seconds": result.duration_seconds,
            "winners": result.winners,
            "output_directory": str(result.config.output_directory) if result.config.output_directory else None,
            "command": result.command,
        }
        self._append_output("\n=== RESULT SUMMARY ===\n")
        self._append_output(json.dumps(summary, indent=2) + "\n")
        if not self.stream_output_var.get():
            if result.stdout:
                self._append_output("\n=== STDOUT ===\n" + result.stdout + "\n")
            if result.stderr:
                self._append_output("\n=== STDERR ===\n" + result.stderr + "\n")

    def _handle_batch_complete(self, summary) -> None:
        self.status_var.set("Batch run complete.")
        self.live_log_window.set_status("Batch run complete.")
        self._append_output("\n=== BATCH SUMMARY ===\n")
        self._append_output(json.dumps(summary.to_jsonable(), indent=2) + "\n")

    def _handle_yaml_complete(self, summaries) -> None:
        self.status_var.set("YAML batch complete.")
        self.live_log_window.set_status("YAML batch complete.")
        self._append_output("\n=== YAML SUMMARY ===\n")
        self._append_output(json.dumps(summaries, indent=2) + "\n")

    def _handle_error(self, traceback_text: str) -> None:
        self.status_var.set("Error during simulation.")
        self.live_log_window.set_status("Error during simulation.")
        self._append_output("\n=== ERROR ===\n" + traceback_text + "\n")
        self.live_log_window.append("\n=== ERROR ===\n" + traceback_text + "\n")
        messagebox.showerror("Simulation Error", traceback_text)


def launch() -> None:
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    ForgeSimLabApp(root)
    root.mainloop()
