"""
Configuration management for Antigravity CLI.

Loads configuration from (in order of priority):
  1. ~/.antigravity/config.yaml
  2. ./config.yaml (project-local override)
  3. Built-in defaults
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class OllamaConfig:
    host: str = "http://192.168.1.136:11434/v1"
    model: str = "llama3.1:8b"
    context_size: int = 8192
    temperature: float = 0.1
    timeout: int = 120


@dataclass
class AgentConfig:
    max_tool_iterations: int = 10
    dangerous_commands_require_confirm: bool = True
    session_save_path: str = "~/.agente/sessions"
    max_saved_sessions: int = 50


@dataclass
class DisplayConfig:
    theme: str = "monokai"
    show_tool_calls: bool = True
    show_thinking: bool = True


@dataclass
class Config:
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)

    @property
    def session_dir(self) -> Path:
        return Path(self.agent.session_save_path).expanduser()


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_CONFIG_SEARCH_PATHS = [
    Path("~/.agente/config.yaml").expanduser(),
    Path("./config.yaml"),
]


def _merge_dict(base: dict, override: dict) -> dict:
    """Deep-merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as e:
        print(f"[config] Warning: could not parse {path}: {e}")
        return {}


def load_config() -> Config:
    """Load and merge configuration from all sources."""
    raw: dict = {}
    for path in _CONFIG_SEARCH_PATHS:
        file_data = _load_yaml(path)
        if file_data:
            raw = _merge_dict(raw, file_data)

    # Apply environment variable overrides
    if host := os.environ.get("ANTIGRAVITY_OLLAMA_HOST"):
        raw.setdefault("ollama", {})["host"] = host
    if model := os.environ.get("ANTIGRAVITY_MODEL"):
        raw.setdefault("ollama", {})["model"] = model

    config = Config()

    if "ollama" in raw:
        o = raw["ollama"]
        config.ollama = OllamaConfig(
            host=o.get("host", config.ollama.host),
            model=o.get("model", config.ollama.model),
            context_size=o.get("context_size", config.ollama.context_size),
            temperature=o.get("temperature", config.ollama.temperature),
            timeout=o.get("timeout", config.ollama.timeout),
        )

    if "agent" in raw:
        a = raw["agent"]
        config.agent = AgentConfig(
            max_tool_iterations=a.get("max_tool_iterations", config.agent.max_tool_iterations),
            dangerous_commands_require_confirm=a.get(
                "dangerous_commands_require_confirm",
                config.agent.dangerous_commands_require_confirm,
            ),
            session_save_path=a.get("session_save_path", config.agent.session_save_path),
            max_saved_sessions=a.get("max_saved_sessions", config.agent.max_saved_sessions),
        )

    if "display" in raw:
        d = raw["display"]
        config.display = DisplayConfig(
            theme=d.get("theme", config.display.theme),
            show_tool_calls=d.get("show_tool_calls", config.display.show_tool_calls),
            show_thinking=d.get("show_thinking", config.display.show_thinking),
        )

    return config
