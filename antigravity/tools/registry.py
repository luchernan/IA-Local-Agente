"""
Tool Registry — Central dispatcher for all agent tools.

Registers all available tools and generates the system prompt section
that describes them to the LLM. Also dispatches tool calls received
from the orchestrator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

from agente.tools import shell, filesystem, navigator
from agente.config import Config


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    tool: str
    args: dict[str, Any]
    raw: str  # original JSON string from model


class ToolRegistry:
    def __init__(self, config: Config, nav: navigator.Navigator):
        self._config = config
        self._nav = nav
        self._handlers: dict[str, Callable] = {
            "shell": self._handle_shell,
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "patch_file": self._handle_patch_file,
            "list_dir": self._handle_list_dir,
            "get_cwd": self._handle_get_cwd,
            "set_cwd": self._handle_set_cwd,
            "find_files": self._handle_find_files,
        }

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def execute(self, call: ToolCall) -> str:
        """Execute a tool call and return the result string."""
        handler = self._handlers.get(call.tool)
        if handler is None:
            available = ", ".join(sorted(self._handlers.keys()))
            return f"Error: Unknown tool '{call.tool}'. Available tools: {available}"
        try:
            result = await handler(call.args)
            return str(result)
        except Exception as e:
            return f"Error executing tool '{call.tool}': {e}"

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_shell(self, args: dict) -> str:
        command = args.get("command", "")
        if not command:
            return "Error: 'command' argument is required."
        timeout = int(args.get("timeout", 30))

        # Dangerous command confirmation is handled in orchestrator
        result = await shell.run_command(
            command=command,
            cwd=self._nav.cwd,
            timeout=timeout,
        )
        return result.to_tool_result()

    async def _handle_read_file(self, args: dict) -> str:
        path = args.get("path", "")
        if not path:
            return "Error: 'path' argument is required."
        return filesystem.read_file(path, cwd=self._nav.cwd)

    async def _handle_write_file(self, args: dict) -> str:
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            return "Error: 'path' argument is required."
        return filesystem.write_file(path, content, cwd=self._nav.cwd)

    async def _handle_patch_file(self, args: dict) -> str:
        path = args.get("path", "")
        old = args.get("old_content", "")
        new = args.get("new_content", "")
        if not path or not old:
            return "Error: 'path' and 'old_content' are required."
        return filesystem.patch_file(path, old, new, cwd=self._nav.cwd)

    async def _handle_list_dir(self, args: dict) -> str:
        path = args.get("path", ".")
        return filesystem.list_dir(path, cwd=self._nav.cwd)

    async def _handle_get_cwd(self, args: dict) -> str:
        return self._nav.get_cwd()

    async def _handle_set_cwd(self, args: dict) -> str:
        path = args.get("path", "")
        if not path:
            return "Error: 'path' argument is required."
        return self._nav.set_cwd(path)

    async def _handle_find_files(self, args: dict) -> str:
        pattern = args.get("pattern", "")
        if not pattern:
            return "Error: 'pattern' argument is required."
        path = args.get("path")
        return self._nav.find_files(pattern, path=path)

    # ------------------------------------------------------------------
    # System prompt generation
    # ------------------------------------------------------------------

    def build_tools_description(self) -> str:
        """
        Generate a human-readable description of all tools for the system prompt.
        """
        all_defs = (
            [shell.TOOL_DEFINITION]
            + filesystem.TOOL_DEFINITIONS
            + navigator.TOOL_DEFINITIONS
        )

        lines = []
        for tool_def in all_defs:
            name = tool_def["name"]
            desc = tool_def["description"]
            args = tool_def.get("args", {})
            example = tool_def.get("example", {})

            lines.append(f"### {name}")
            lines.append(desc)
            if args:
                lines.append("Arguments:")
                for arg_name, arg_info in args.items():
                    req = "required" if arg_info.get("required") else "optional"
                    lines.append(f"  - {arg_name} ({arg_info['type']}, {req}): {arg_info['description']}")
            if example:
                lines.append(f"Example: {json.dumps(example)}")
            lines.append("")

        return "\n".join(lines)

    def is_dangerous(self, call: ToolCall) -> bool:
        """Return True if this tool call requires user confirmation."""
        if call.tool == "shell":
            command = call.args.get("command", "")
            return shell.is_dangerous(command)
        return False
