"""Chamadas curtas ao WSL, usadas pelo Ollama e pelo Kraken."""
from __future__ import annotations

import shlex
import subprocess


def run(script: str, *, timeout: float = 10) -> str | None:
    try:
        completed = subprocess.run(
            ["wsl", "-e", "bash", "-lc", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = completed.stdout.strip()
    if completed.returncode != 0 and not text:
        return None
    return text or None


def eth0_ip() -> str | None:
    output = run("ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1", timeout=5)
    if not output:
        return None
    return output.splitlines()[0].strip() or None


def home() -> str | None:
    return run('printf %s "$HOME"')


def is_executable(path: str) -> bool:
    return run(f"test -x {shlex.quote(path)} && echo ok") == "ok"
