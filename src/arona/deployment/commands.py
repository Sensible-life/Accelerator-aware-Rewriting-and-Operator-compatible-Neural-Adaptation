"""Auditable subprocess execution used by deployment stages."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CommandOutcome:
    command: tuple[str, ...]
    working_directory: Path
    exit_code: int | None
    duration_ms: float
    stdout: str
    stderr: str
    timed_out: bool = False


class CommandRunner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        working_directory: Path,
        timeout_seconds: int,
        environment: dict[str, str] | None = None,
    ) -> CommandOutcome:
        """Execute one command without a shell and return all observable output."""


class SubprocessCommandRunner:
    def run(
        self,
        command: list[str],
        *,
        working_directory: Path,
        timeout_seconds: int,
        environment: dict[str, str] | None = None,
    ) -> CommandOutcome:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=working_directory,
                env=environment,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
            return CommandOutcome(
                command=tuple(command),
                working_directory=working_directory,
                exit_code=completed.returncode,
                duration_ms=(time.monotonic() - started) * 1000,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        except subprocess.TimeoutExpired as error:
            return CommandOutcome(
                command=tuple(command),
                working_directory=working_directory,
                exit_code=None,
                duration_ms=(time.monotonic() - started) * 1000,
                stdout=_timeout_text(error.stdout),
                stderr=_timeout_text(error.stderr),
                timed_out=True,
            )


def write_command_log(outcome: CommandOutcome, path: Path) -> Path:
    """Persist a deterministic JSON command envelope and raw streams."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "command": list(outcome.command),
                "working_directory": str(outcome.working_directory),
                "exit_code": outcome.exit_code,
                "duration_ms": outcome.duration_ms,
                "timed_out": outcome.timed_out,
                "stdout": outcome.stdout,
                "stderr": outcome.stderr,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def first_error(outcome: CommandOutcome) -> str | None:
    if outcome.timed_out:
        return "Command timed out."
    for stream in (outcome.stderr, outcome.stdout):
        lines = [line.strip() for line in stream.splitlines() if line.strip()]
        for line in lines:
            if "error" in line.lower() or "failed" in line.lower():
                return line
        if lines and outcome.exit_code not in {None, 0}:
            return lines[0]
    return None


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value
