"""
Orchestrator — Core Agent Loop (ReAct: Reason → Act → Observe).

Coordinates the LLM, tool execution, context management, and session
persistence. This is the brain of the agent.

Tool Call Protocol:
  The model signals tool use by outputting a special XML-like block:

    <tool_call>
    {"tool": "shell", "args": {"command": "ls -la"}}
    </tool_call>

  The orchestrator detects this pattern, executes the tool, injects
  the result into context, and loops the LLM until no more tool calls
  are produced.
"""

from __future__ import annotations

import json
import re
import asyncio
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, AsyncIterator, Callable, Optional

from agente.config import Config
from agente.llm.client import OllamaClient
from agente.llm.context import ContextManager
from agente.tools.registry import ToolRegistry, ToolCall
from agente.tools.navigator import Navigator


# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are Antigravity, an expert AI coding agent running in a Linux terminal (Kali Linux).
You can reason step-by-step and interact with the system through tools.

## Tool Usage Protocol

When you need to use a tool, output EXACTLY this format on its own (no extra text around it):

<tool_call>
{{"tool": "<tool_name>", "args": {{<args_as_json>}}}}
</tool_call>

Rules:
- Output ONE tool call at a time.
- Do NOT fabricate tool results. Always wait for the real output.
- After receiving a tool result, continue reasoning or answer the user.
- If a task requires multiple steps, use tools sequentially.
- Always prefer using tools to get accurate, real information rather than guessing.

## Available Tools

{tools_description}

## Behavior Guidelines

- Think step by step before acting.
- Respond in the SAME LANGUAGE the user uses (Spanish if they write in Spanish).
- For destructive or irreversible operations, briefly explain what you're about to do.
- When writing code, prefer clear, well-commented solutions.
- When you finish a task, summarize what you did concisely.
- Your current working directory: {cwd}
"""

# ---------------------------------------------------------------------------
# Tool call parsing
# ---------------------------------------------------------------------------

_TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)


def parse_tool_call(text: str) -> Optional[ToolCall]:
    """
    Extract and parse a <tool_call>...</tool_call> block from model output.

    Returns a ToolCall or None if not found / invalid JSON.
    """
    match = _TOOL_CALL_PATTERN.search(text)
    if not match:
        return None
    raw_json = match.group(1).strip()
    try:
        data = json.loads(raw_json)
        tool_name = data.get("tool", "")
        args = data.get("args", {})
        if not tool_name:
            return None
        return ToolCall(tool=tool_name, args=args, raw=raw_json)
    except json.JSONDecodeError:
        return None


def strip_tool_call_block(text: str) -> str:
    """Remove the <tool_call>...</tool_call> block from the text."""
    return _TOOL_CALL_PATTERN.sub("", text).strip()


# ---------------------------------------------------------------------------
# Events emitted by the orchestrator
# ---------------------------------------------------------------------------

class OrchestratorEvent:
    """Base class for events emitted during agent loop execution."""


class TextTokenEvent(OrchestratorEvent):
    """A text token from the LLM that should be displayed."""
    def __init__(self, token: str):
        self.token = token


class ToolStartEvent(OrchestratorEvent):
    """The agent is about to execute a tool."""
    def __init__(self, call: ToolCall):
        self.call = call


class ToolResultEvent(OrchestratorEvent):
    """A tool finished executing."""
    def __init__(self, call: ToolCall, result: str):
        self.call = call
        self.result = result


class ConfirmationRequiredEvent(OrchestratorEvent):
    """The orchestrator needs user confirmation before proceeding."""
    def __init__(self, call: ToolCall, prompt: str):
        self.call = call
        self.prompt = prompt


class ErrorEvent(OrchestratorEvent):
    """An error occurred."""
    def __init__(self, message: str):
        self.message = message


class DoneEvent(OrchestratorEvent):
    """The agent has finished processing a user turn."""
    def __init__(self, full_response: str):
        self.full_response = full_response


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Core agent loop. Manages conversation state and tool execution.

    Usage:
        async for event in orchestrator.run_turn(user_message):
            # handle events (stream to terminal, show tool calls, etc.)
    """

    def __init__(
        self,
        config: Config,
        confirm_callback: Optional[Callable[[str], bool]] = None,
    ):
        self._config = config
        self._confirm_callback = confirm_callback  # For dangerous commands

        # Sub-components
        self._nav = Navigator()
        self._client = OllamaClient(config)
        self._registry = ToolRegistry(config, self._nav)

        # Build initial system prompt
        system_prompt = self._build_system_prompt()
        self._context = ContextManager(
            max_tokens=config.ollama.context_size,
            system_prompt=system_prompt,
        )

        # Session metadata
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._turn_count = 0

    def _build_system_prompt(self) -> str:
        tools_desc = self._registry.build_tools_description()
        return SYSTEM_PROMPT_TEMPLATE.format(
            tools_description=tools_desc,
            cwd=self._nav.cwd,
        )

    def _refresh_system_prompt(self) -> None:
        """Update system prompt with current cwd (changes after set_cwd calls)."""
        self._context.update_system_prompt(self._build_system_prompt())

    async def run_turn(
        self, user_message: str
    ) -> AsyncGenerator[OrchestratorEvent, None]:
        """
        Process one user turn through the ReAct loop.

        Yields OrchestratorEvent objects for the CLI to display.
        """
        self._turn_count += 1
        self._context.add_user_message(user_message)

        iterations = 0
        full_assistant_response = ""

        while iterations < self._config.agent.max_tool_iterations:
            iterations += 1

            # --- Stream LLM response ---
            messages = self._context.get_messages()
            buffered = ""
            pre_tool_text = ""
            tool_call_detected = False

            try:
                async for token in self._client.chat_stream(messages):
                    buffered += token

                    # Check if we're accumulating a tool_call block
                    if "<tool_call>" in buffered:
                        if not tool_call_detected:
                            # Yield any text before the tool call tag
                            pre_tool_text = buffered.split("<tool_call>")[0]
                            if pre_tool_text.strip():
                                yield TextTokenEvent(pre_tool_text)
                            tool_call_detected = True
                        # Don't yield while accumulating tool call
                        if "</tool_call>" in buffered:
                            break  # tool call block complete, exit stream loop
                    else:
                        # Pure text — yield token for live streaming
                        if not tool_call_detected:
                            yield TextTokenEvent(token)

            except ConnectionError as e:
                yield ErrorEvent(str(e))
                return
            except TimeoutError as e:
                yield ErrorEvent(str(e))
                return
            except Exception as e:
                yield ErrorEvent(f"LLM error: {e}")
                return

            # --- Parse buffered response for tool calls ---
            tool_call = parse_tool_call(buffered)

            if tool_call is None:
                # No tool call — this is the final response
                if tool_call_detected:
                    # We detected <tool_call> but couldn't parse it
                    # Show the full text as-is
                    yield TextTokenEvent(buffered)
                # else: text was already streamed token-by-token

                # Add to context and finish turn
                self._context.add_assistant_message(buffered)
                full_assistant_response = buffered
                break

            # --- Tool call detected ---
            # The text before the tool call was already yielded above

            # Check for dangerous commands
            if (
                self._config.agent.dangerous_commands_require_confirm
                and self._registry.is_dangerous(tool_call)
            ):
                yield ConfirmationRequiredEvent(
                    call=tool_call,
                    prompt=f"⚠️  Dangerous command detected: `{tool_call.args.get('command', '')}`\nProceed? [y/N]",
                )
                # The CLI will handle confirmation and call confirm_tool()
                # For now, we pause via an asyncio.Event (see confirm_tool method)
                confirmed = await self._wait_for_confirmation()
                if not confirmed:
                    self._context.add_assistant_message(
                        strip_tool_call_block(buffered)
                        + "\n[Tool execution cancelled by user.]"
                    )
                    yield DoneEvent(full_assistant_response)
                    return

            # Execute tool
            yield ToolStartEvent(tool_call)
            result = await self._registry.execute(tool_call)
            yield ToolResultEvent(tool_call, result)

            # Add assistant turn (including the tool call) and tool result to context
            self._context.add_assistant_message(buffered)
            self._context.add_tool_result(tool_call.tool, result)

            # Update cwd in system prompt after navigation
            if tool_call.tool == "set_cwd":
                self._refresh_system_prompt()

            # Continue the loop for next LLM iteration
            full_assistant_response += f"\n[Used tool: {tool_call.tool}]"

        else:
            # Max iterations reached
            yield ErrorEvent(
                f"⚠️  Reached maximum tool iterations ({self._config.agent.max_tool_iterations}). "
                "Stopping to prevent infinite loop."
            )

        yield DoneEvent(full_assistant_response)

    # ------------------------------------------------------------------
    # Confirmation mechanism
    # ------------------------------------------------------------------

    _confirm_result: Optional[bool] = None
    _confirm_event: Optional[asyncio.Event] = None

    async def _wait_for_confirmation(self) -> bool:
        """Block until CLI calls confirm_tool() with user's decision."""
        self._confirm_event = asyncio.Event()
        self._confirm_result = None
        await self._confirm_event.wait()
        return self._confirm_result or False

    def confirm_tool(self, confirmed: bool) -> None:
        """Called by the CLI to resolve a pending confirmation."""
        self._confirm_result = confirmed
        if self._confirm_event:
            self._confirm_event.set()

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def save_session(self) -> Optional[Path]:
        """Save the current conversation to disk. Returns path to saved file."""
        try:
            session_dir = self._config.session_dir
            session_dir.mkdir(parents=True, exist_ok=True)

            session_file = session_dir / f"session_{self.session_id}.json"
            data = {
                "session_id": self.session_id,
                "model": self._config.ollama.model,
                "created_at": self.session_id,
                "turn_count": self._turn_count,
                "cwd": self._nav.cwd,
                "history": self._context.get_history_snapshot(),
            }
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return session_file
        except Exception:
            return None

    def load_session(self, session_file: Path) -> bool:
        """Load a conversation from a session file. Returns True on success."""
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            history = data.get("history", [])
            self._context.load_history(history)
            if cwd := data.get("cwd"):
                self._nav.set_cwd(cwd)
                self._refresh_system_prompt()
            self.session_id = data.get("session_id", self.session_id)
            self._turn_count = data.get("turn_count", 0)
            return True
        except Exception:
            return False

    def list_sessions(self) -> list[Path]:
        """Return list of saved session files, newest first."""
        session_dir = self._config.session_dir
        if not session_dir.exists():
            return []
        return sorted(session_dir.glob("session_*.json"), reverse=True)

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    @property
    def cwd(self) -> str:
        return self._nav.cwd

    @property
    def token_usage(self) -> dict:
        return self._context.token_usage()

    @property
    def model(self) -> str:
        return self._config.ollama.model
