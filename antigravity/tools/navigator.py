"""
Navigator tool — Manage the agent's working directory and file search.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class Navigator:
    """Maintains the agent's working directory across tool calls."""

    def __init__(self, initial_cwd: Optional[str] = None):
        self._cwd = Path(initial_cwd or os.getcwd()).resolve()

    @property
    def cwd(self) -> str:
        return str(self._cwd)

    def get_cwd(self) -> str:
        """Return the current working directory."""
        return str(self._cwd)

    def set_cwd(self, path: str) -> str:
        """
        Change the agent's working directory.

        Returns a success or error message.
        """
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = self._cwd / target
        target = target.resolve()

        if not target.exists():
            return f"Error: Directory does not exist: {target}"
        if not target.is_dir():
            return f"Error: Not a directory: {target}"

        self._cwd = target
        return f"✓ Working directory changed to: {target}"

    def find_files(
        self,
        pattern: str,
        path: Optional[str] = None,
        max_results: int = 50,
    ) -> str:
        """
        Find files matching a glob pattern recursively.

        Args:
            pattern: Glob pattern (e.g., "*.py", "**/*.json", "main*")
            path: Starting directory (default: cwd)
            max_results: Maximum number of results to return

        Returns:
            Formatted list of matching paths.
        """
        search_root = Path(path or self._cwd).expanduser()
        if not search_root.is_absolute():
            search_root = self._cwd / search_root
        search_root = search_root.resolve()

        if not search_root.exists():
            return f"Error: Directory not found: {search_root}"

        matches = []
        try:
            for entry in search_root.rglob("*"):
                # Skip hidden dirs and common noise
                parts = entry.parts
                if any(p.startswith(".") for p in parts) or any(
                    p in ("__pycache__", "node_modules", ".git", "venv", ".venv")
                    for p in parts
                ):
                    continue
                if fnmatch.fnmatch(entry.name, pattern):
                    matches.append(entry)
                if len(matches) >= max_results:
                    break
        except PermissionError:
            pass

        if not matches:
            return f"No files matching '{pattern}' found in {search_root}"

        lines = [f"Found {len(matches)} file(s) matching '{pattern}':"]
        for m in sorted(matches):
            try:
                rel = m.relative_to(self._cwd)
                lines.append(f"  {rel}")
            except ValueError:
                lines.append(f"  {m}")

        if len(matches) >= max_results:
            lines.append(f"  ... (showing first {max_results} results)")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool definitions (used by registry)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "get_cwd",
        "description": "Get the current working directory of the agent.",
        "args": {},
        "example": {"tool": "get_cwd", "args": {}},
    },
    {
        "name": "set_cwd",
        "description": "Change the agent's working directory.",
        "args": {
            "path": {
                "type": "string",
                "description": "Directory path to change to (absolute or relative).",
                "required": True,
            }
        },
        "example": {"tool": "set_cwd", "args": {"path": "/home/user/myproject"}},
    },
    {
        "name": "find_files",
        "description": (
            "Recursively search for files matching a glob pattern. "
            "Useful for finding Python files, configs, etc."
        ),
        "args": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match filenames (e.g. '*.py', 'main*', '*.json').",
                "required": True,
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: current directory).",
                "required": False,
            },
        },
        "example": {"tool": "find_files", "args": {"pattern": "*.py"}},
    },
]
