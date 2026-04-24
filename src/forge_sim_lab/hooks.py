from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping


def run_shell_hook(command: str, *, cwd: Path | None = None, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update({k: str(v) for k, v in env.items()})
    return subprocess.run(
        command,
        shell=True,
        executable="/bin/bash",
        cwd=str(cwd) if cwd else None,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
    )
