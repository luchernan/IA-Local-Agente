"""
Shell tool — Execute system commands safely.

Supports Linux (bash/sh) with timeout, dangerous command detection,
and structured output capture.
"""

from __future__ import annotations

import asyncio
import re
import shlex
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Dangerous command patterns (require user confirmation)
# ---------------------------------------------------------------------------

_DANGEROUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"\brm\s+-rf?\b"),
    re.compile(r"\bdd\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bformat\b"),
    re.compile(r"\bshred\b"),
    re.compile(r"\bwipe\b"),
    re.compile(r"\bfdisk\b"),
    re.compile(r"\bparted\b"),
    re.compile(r">\s*/dev/[sh]d[a-z]"),
    re.compile(r"\bchmod\s+777\b"),
    re.compile(r"\bsudo\s+rm\b"),
    re.compile(r"\bcurl.*\|\s*(bash|sh)\b"),
    re.compile(r"\bwget.*\|\s*(bash|sh)\b"),
]

_TIMEOUT_DEFAULT = 30  # seconds


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ShellResult:
    command: str
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False

    @property
    def output(self) -> str:
        """Combined stdout + stderr."""
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout)
        if self.stderr.strip():
            parts.append(f"[stderr]\n{self.stderr}")
        return "\n".join(parts) if parts else "(no output)"

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_tool_result(self) -> str:
        lines = [f"$ {self.command}"]
        if self.timed_out:
            lines.append("⚠️  Command timed out.")
        lines.append(self.output)
        if not self.success and not self.timed_out:
            lines.append(f"Exit code: {self.returncode}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def is_dangerous(command: str) -> bool:
    """Return True if command matches any dangerous pattern."""
    return any(p.search(command) for p in _DANGEROUS_PATTERNS)


async def run_command(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = _TIMEOUT_DEFAULT,
    env: Optional[dict] = None,
) -> ShellResult:
    """
    Execute a shell command asynchronously.

    Args:
        command: Shell command string (executed via /bin/bash -c)
        cwd: Working directory for the command
        timeout: Timeout in seconds
        env: Additional environment variables

    Returns:
        ShellResult with stdout, stderr, returncode
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            executable="/bin/bash",
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return ShellResult(
                command=command,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                returncode=proc.returncode or 0,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return ShellResult(
                command=command,
                stdout="",
                stderr="",
                returncode=-1,
                timed_out=True,
            )

    except Exception as e:
        return ShellResult(
            command=command,
            stdout="",
            stderr=str(e),
            returncode=-1,
        )


# ---------------------------------------------------------------------------
# Tool definition (used by registry)
# ---------------------------------------------------------------------------

TOOL_DEFINITION = {
    "name": "shell",
    "description": (
        "Execute a shell command on the system. "
        "Use for running scripts, installing packages, compiling code, "
        "checking system state, git operations, etc."
    ),
    "args": {
        "command": {
            "type": "string",
            "description": "The shell command to execute. Runs in bash.",
            "required": True,
        },
        "timeout": {
            "type": "integer",
            "description": f"Timeout in seconds (default: {_TIMEOUT_DEFAULT}).",
            "required": False,
        },
    },
    "example": {
        "tool": "shell",
        "args": {"command": "ls -la /home"},
    },
}
