"""
Filesystem tool — Read, write, patch and list files.

All operations are relative to the agent's current working directory
unless an absolute path is provided.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

_MAX_READ_BYTES = 100_000   # ~100KB max read per file
_MAX_LIST_ENTRIES = 200     # max directory entries to show


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def read_file(path: str, cwd: Optional[str] = None, encoding: str = "utf-8") -> str:
    """
    Read the contents of a file.

    Returns file contents as string, or an error message.
    """
    try:
        resolved = _resolve(path, cwd)
        size = resolved.stat().st_size
        if size > _MAX_READ_BYTES:
            # Read first chunk and warn
            with open(resolved, "r", encoding=encoding, errors="replace") as f:
                content = f.read(_MAX_READ_BYTES)
            return (
                content
                + f"\n\n... [truncated — file is {size:,} bytes, showing first {_MAX_READ_BYTES:,}]"
            )
        with open(resolved, "r", encoding=encoding, errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except PermissionError:
        return f"Error: Permission denied reading: {path}"
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(path: str, content: str, cwd: Optional[str] = None, encoding: str = "utf-8") -> str:
    """
    Write content to a file, creating parent directories if needed.

    Returns a success or error message.
    """
    try:
        resolved = _resolve(path, cwd)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with open(resolved, "w", encoding=encoding) as f:
            f.write(content)
        lines = content.count("\n") + (1 if content else 0)
        return f"✓ Written {lines} lines ({len(content):,} bytes) to {resolved}"
    except PermissionError:
        return f"Error: Permission denied writing to: {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def patch_file(path: str, old_content: str, new_content: str, cwd: Optional[str] = None) -> str:
    """
    Replace an exact string in a file (first occurrence).

    Returns success/error message and shows what changed.
    """
    try:
        resolved = _resolve(path, cwd)
        original = resolved.read_text(encoding="utf-8", errors="replace")

        if old_content not in original:
            # Try to provide a helpful error
            short = old_content[:80].replace("\n", "\\n")
            return (
                f"Error: Could not find the target text in {path}.\n"
                f"Target started with: '{short}...'"
            )

        patched = original.replace(old_content, new_content, 1)
        resolved.write_text(patched, encoding="utf-8")
        return f"✓ Patched {path} — replaced {len(old_content)} chars with {len(new_content)} chars."
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error patching file: {e}"


def list_dir(path: str = ".", cwd: Optional[str] = None) -> str:
    """
    List directory contents with metadata (type, size, permissions).
    """
    try:
        resolved = _resolve(path, cwd)
        if not resolved.is_dir():
            return f"Error: Not a directory: {path}"

        entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        if not entries:
            return f"(empty directory: {resolved})"

        lines = [f"📁 {resolved}/\n"]
        for i, entry in enumerate(entries[:_MAX_LIST_ENTRIES]):
            try:
                stat = entry.stat()
                if entry.is_dir():
                    icon = "📂"
                    size_str = ""
                elif entry.is_symlink():
                    icon = "🔗"
                    size_str = f"  → {os.readlink(entry)}"
                else:
                    icon = _file_icon(entry.suffix)
                    size_str = f"  {_human_size(stat.st_size)}"

                perm = oct(stat.st_mode)[-3:]
                lines.append(f"  {icon} {entry.name}{size_str}  [{perm}]")
            except (PermissionError, OSError):
                lines.append(f"  ❓ {entry.name}  [inaccessible]")

        if len(entries) > _MAX_LIST_ENTRIES:
            lines.append(f"\n  ... and {len(entries) - _MAX_LIST_ENTRIES} more entries")

        return "\n".join(lines)
    except FileNotFoundError:
        return f"Error: Directory not found: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error listing directory: {e}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve(path: str, cwd: Optional[str]) -> Path:
    p = Path(path)
    if not p.is_absolute() and cwd:
        p = Path(cwd) / p
    return p.resolve()


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _file_icon(suffix: str) -> str:
    icons = {
        ".py": "🐍", ".js": "🟨", ".ts": "🔷", ".rs": "🦀",
        ".go": "🐹", ".sh": "📜", ".md": "📝", ".txt": "📄",
        ".json": "🗂️", ".yaml": "⚙️", ".yml": "⚙️", ".toml": "⚙️",
        ".html": "🌐", ".css": "🎨", ".sql": "🗃️", ".c": "🔵",
        ".cpp": "🔵", ".h": "🔵", ".java": "☕", ".rb": "💎",
        ".dockerfile": "🐳", ".gitignore": "🙈",
    }
    return icons.get(suffix.lower(), "📄")


# ---------------------------------------------------------------------------
# Tool definitions (used by registry)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns the file content as text.",
        "args": {
            "path": {
                "type": "string",
                "description": "Path to the file (absolute or relative to cwd).",
                "required": True,
            }
        },
        "example": {"tool": "read_file", "args": {"path": "main.py"}},
    },
    {
        "name": "write_file",
        "description": (
            "Write content to a file, creating it if it doesn't exist. "
            "Overwrites existing content. Use for creating new files or replacing entire file content."
        ),
        "args": {
            "path": {
                "type": "string",
                "description": "Path to the file.",
                "required": True,
            },
            "content": {
                "type": "string",
                "description": "Full content to write to the file.",
                "required": True,
            },
        },
        "example": {
            "tool": "write_file",
            "args": {"path": "hello.py", "content": "print('Hello, world!')"},
        },
    },
    {
        "name": "patch_file",
        "description": (
            "Replace an exact text snippet in a file. "
            "Use when you only need to change a specific part of a file. "
            "The old_content must match exactly (including whitespace/indentation)."
        ),
        "args": {
            "path": {
                "type": "string",
                "description": "Path to the file.",
                "required": True,
            },
            "old_content": {
                "type": "string",
                "description": "Exact text to find and replace.",
                "required": True,
            },
            "new_content": {
                "type": "string",
                "description": "Text to replace it with.",
                "required": True,
            },
        },
        "example": {
            "tool": "patch_file",
            "args": {
                "path": "main.py",
                "old_content": "print('Hello')",
                "new_content": "print('Hello, world!')",
            },
        },
    },
    {
        "name": "list_dir",
        "description": "List the contents of a directory with file sizes and permissions.",
        "args": {
            "path": {
                "type": "string",
                "description": "Directory path (default: current directory).",
                "required": False,
            }
        },
        "example": {"tool": "list_dir", "args": {"path": "."}},
    },
]
