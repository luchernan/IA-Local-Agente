"""
Context management — Sliding window conversation history with token estimation.

Keeps the conversation within the model's context window by pruning
old messages when the estimated token count approaches the limit.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Optional


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """
    Fast token count estimation without a tokenizer.
    Approximation: ~4 characters per token (conservative for code/English mix).
    """
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content) + 4  # role overhead
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += estimate_tokens(part.get("text", "")) + 4
    return total


# ---------------------------------------------------------------------------
# Truncation helpers
# ---------------------------------------------------------------------------

_MAX_TOOL_RESULT_CHARS = 4000  # Truncate very long tool results


def truncate_tool_result(content: str, max_chars: int = _MAX_TOOL_RESULT_CHARS) -> str:
    """Truncate a tool result that is too long, keeping the end (usually more relevant)."""
    if len(content) <= max_chars:
        return content
    head = content[:max_chars // 4]
    tail = content[-(max_chars * 3 // 4):]
    removed = len(content) - len(head) - len(tail)
    return f"{head}\n\n... [{removed:,} characters omitted] ...\n\n{tail}"


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class ContextManager:
    """
    Manages the message history for the LLM, respecting context size limits.

    The system prompt is always kept as the first message.
    A sliding window prunes the oldest non-system messages when needed.
    """

    def __init__(self, max_tokens: int, system_prompt: str):
        self.max_tokens = max_tokens
        self._system_prompt = system_prompt
        self._history: list[dict] = []  # excludes system message

    @property
    def system_message(self) -> dict:
        return {"role": "system", "content": self._system_prompt}

    def update_system_prompt(self, new_prompt: str) -> None:
        self._system_prompt = new_prompt

    def add_user_message(self, content: str) -> None:
        self._history.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self._history.append({"role": "assistant", "content": content})

    def add_tool_result(self, tool_name: str, result: str) -> None:
        """Inject a tool result as a user message."""
        truncated = truncate_tool_result(result)
        self._history.append({
            "role": "user",
            "content": f"[Tool Result: {tool_name}]\n{truncated}",
        })

    def get_messages(self) -> list[dict]:
        """
        Return the full message list ready to send to the LLM.

        Applies sliding window if approaching context limit.
        """
        messages = [self.system_message] + deepcopy(self._history)
        messages = self._apply_sliding_window(messages)
        return messages

    def _apply_sliding_window(self, messages: list[dict]) -> list[dict]:
        """
        Prune oldest non-system messages until we're under the token budget.
        Always keeps: system message + last 2 exchanges minimum.
        """
        safety_margin = 512  # leave room for the response
        budget = self.max_tokens - safety_margin

        while len(messages) > 3:  # system + at least 1 user + 1 assistant
            total = estimate_messages_tokens(messages)
            if total <= budget:
                break
            # Remove the second message (index 1), keeping system first
            messages.pop(1)

        return messages

    def get_history_snapshot(self) -> list[dict]:
        """Return a copy of the raw history (for session saving)."""
        return deepcopy(self._history)

    def load_history(self, history: list[dict]) -> None:
        """Restore history from a saved session."""
        self._history = deepcopy(history)

    def clear(self) -> None:
        """Clear conversation history (keeps system prompt)."""
        self._history = []

    def token_usage(self) -> dict:
        """Return current token usage statistics."""
        sys_tokens = estimate_tokens(self._system_prompt)
        hist_tokens = estimate_messages_tokens(self._history)
        total = sys_tokens + hist_tokens
        return {
            "system": sys_tokens,
            "history": hist_tokens,
            "total": total,
            "limit": self.max_tokens,
            "usage_pct": round(total / self.max_tokens * 100, 1),
        }
