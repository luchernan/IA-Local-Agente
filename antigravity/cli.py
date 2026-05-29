"""
Antigravity CLI — Terminal interface for the AI coding agent.

Rich rendering + prompt_toolkit for a premium terminal experience:
  - Syntax-highlighted code blocks
  - Markdown rendering
  - Persistent input history (arrow keys)
  - Live streaming output
  - Tool execution panels
  - Session management commands
"""

from __future__ import annotations

import asyncio
import sys
import os
from pathlib import Path
from typing import Optional

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.status import Status
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from antigravity import __version__
from antigravity.config import load_config
from antigravity.orchestrator import (
    Orchestrator,
    TextTokenEvent,
    ToolStartEvent,
    ToolResultEvent,
    ConfirmationRequiredEvent,
    ErrorEvent,
    DoneEvent,
)


# ---------------------------------------------------------------------------
# Theme & Console setup
# ---------------------------------------------------------------------------

CUSTOM_THEME = Theme({
    "agent.name": "bold cyan",
    "agent.bracket": "dim cyan",
    "user.prompt": "bold green",
    "tool.name": "bold yellow",
    "tool.result.ok": "green",
    "tool.result.err": "red",
    "error": "bold red",
    "info": "dim white",
    "dim": "dim",
    "accent": "bold magenta",
    "cwd": "dim blue",
    "token_info": "dim",
})

console = Console(theme=CUSTOM_THEME, highlight=False)


# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------

BANNER = """\
[bold cyan]  ▄████████ ███▄▄▄▄       ███      ▄█   ▄████████    ▄████████  ▄████████ ██▀███   ▄█      ███      ▄██   ▄[/bold cyan]
[cyan] ███    ███ ███▀▀▀██▄  ▀█████████▄ ███  ███    ███   ███    ███ ███    ███ ▓██ ▒ ██▒ ███  ▀█████████▄ ███   ██▄[/cyan]
[bold blue] ███    ███ ███   ███    ▀███▀▀██ ███▌ ███    █▀    ███    ███ ███    ███ ▓██ ░▄█ ▒ ███▌    ▀███▀▀██ ▓███▄███[/bold blue]
[blue] ███    ███ ███   ███     ███   ▀ ███▌ ███         ▄███▄▄▄▄██▀ ▄███▄▄▄▄██▀ ▒██▀▀█▄   ███▌     ███   ▀ ▓▀▀▀▀███[/blue]"""

MINI_BANNER = "[bold cyan]⚡ ANTIGRAVITY[/bold cyan] [dim]— Local AI Coding Agent[/dim]"


def print_banner(compact: bool = False) -> None:
    if compact:
        console.print(MINI_BANNER)
    else:
        console.print()
        console.print(Panel(
            f"[bold cyan]⚡ ANTIGRAVITY[/bold cyan]  [dim]v{__version__}[/dim]\n"
            f"[dim]Local-first AI Coding Agent powered by Ollama[/dim]",
            border_style="cyan",
            padding=(1, 4),
        ))


def print_startup_info(orchestrator: Orchestrator) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="white")
    table.add_row("🤖 Model", f"[bold]{orchestrator.model}[/bold]")
    table.add_row("📁 CWD", f"[blue]{orchestrator.cwd}[/blue]")
    table.add_row("💬 Session", f"[dim]{orchestrator.session_id}[/dim]")
    table.add_row("📖 Help", "[dim]Type /help for commands[/dim]")
    console.print(table)
    console.print()


def render_agent_response(text: str, syntax_theme: str = "monokai") -> None:
    """Render the final agent response with markdown and code highlighting."""
    try:
        md = Markdown(text, code_theme=syntax_theme)
        console.print(md)
    except Exception:
        console.print(text)


def print_tool_start(tool_name: str, args: dict) -> None:
    """Show a compact tool execution indicator."""
    args_str = ", ".join(
        f"{k}={repr(v)[:60]}" for k, v in args.items()
    )
    console.print(
        f"\n[bold yellow]⚙[/bold yellow] [tool.name]{tool_name}[/tool.name]"
        f"[dim]({args_str})[/dim]"
    )


def print_tool_result(tool_name: str, result: str, show: bool = True) -> None:
    """Show a collapsible tool result panel."""
    if not show:
        return
    # Truncate very long results for display
    display_result = result
    if len(result) > 2000:
        display_result = result[:1000] + "\n\n... [truncated for display] ...\n\n" + result[-500:]

    syntax = Syntax(display_result, "bash", theme="monokai", line_numbers=False, word_wrap=True)
    console.print(Panel(
        syntax,
        title=f"[dim]{tool_name} result[/dim]",
        border_style="dim yellow",
        padding=(0, 1),
    ))


def print_error(message: str) -> None:
    console.print(f"\n[error]❌ {message}[/error]\n")


def print_info(message: str) -> None:
    console.print(f"[info]{message}[/info]")


def print_token_status(usage: dict) -> None:
    pct = usage["usage_pct"]
    color = "green" if pct < 60 else "yellow" if pct < 85 else "red"
    console.print(
        f"[token_info]Context: [{color}]{usage['total']:,}[/{color}]/{usage['limit']:,} tokens ({pct}%)[/token_info]",
        end="\n",
    )


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

HELP_TEXT = """
[bold cyan]Antigravity CLI — Available Commands[/bold cyan]

[bold yellow]Conversation[/bold yellow]
  [green]/clear[/green]           Clear conversation history
  [green]/session save[/green]    Save current session to disk
  [green]/session list[/green]    List saved sessions
  [green]/session load <n>[/green] Load a saved session by number
  [green]/tokens[/green]          Show current context token usage

[bold yellow]Navigation[/bold yellow]
  [green]/cwd[/green]             Show current working directory
  [green]/cd <path>[/green]       Change working directory

[bold yellow]System[/bold yellow]
  [green]/model[/green]           Show current model info
  [green]/check[/green]           Check Ollama server connection
  [green]/help[/green]            Show this help message
  [green]/exit[/green], [green]/quit[/green]    Exit Antigravity

[dim]Tip: Use Ctrl+D or Ctrl+C to exit. Use arrow keys for input history.[/dim]
"""


async def handle_slash_command(
    command: str, orchestrator: Orchestrator
) -> bool:
    """
    Handle a /command. Returns True if it was a recognized command.
    """
    parts = command.strip().split(None, 2)
    cmd = parts[0].lower()

    if cmd in ("/exit", "/quit"):
        raise SystemExit(0)

    elif cmd == "/help":
        console.print(Panel(HELP_TEXT, border_style="cyan", title="[cyan]Help[/cyan]"))
        return True

    elif cmd == "/clear":
        orchestrator._context.clear()
        console.print("[info]✓ Conversation cleared.[/info]")
        return True

    elif cmd == "/tokens":
        print_token_status(orchestrator.token_usage)
        return True

    elif cmd == "/cwd":
        console.print(f"[blue]{orchestrator.cwd}[/blue]")
        return True

    elif cmd == "/cd" and len(parts) >= 2:
        result = orchestrator._nav.set_cwd(parts[1])
        orchestrator._refresh_system_prompt()
        console.print(f"[info]{result}[/info]")
        return True

    elif cmd == "/model":
        info_table = Table.grid(padding=(0, 2))
        info_table.add_column(style="dim")
        info_table.add_column(style="white")
        info_table.add_row("Model", orchestrator.model)
        info_table.add_row("Host", orchestrator._config.ollama.host)
        info_table.add_row("Context", f"{orchestrator._config.ollama.context_size:,} tokens")
        info_table.add_row("Temperature", str(orchestrator._config.ollama.temperature))
        console.print(Panel(info_table, title="[cyan]Model Info[/cyan]", border_style="cyan"))
        return True

    elif cmd == "/check":
        with console.status("[cyan]Checking Ollama connection...[/cyan]"):
            result = await orchestrator._client.health_check()
        if result["ok"]:
            models = result.get("models", [])
            console.print(f"[green]✓ Ollama server is reachable.[/green]")
            if models:
                console.print(f"[dim]Available models: {', '.join(models[:10])}[/dim]")
        else:
            console.print(f"[error]✗ Cannot reach Ollama: {result.get('error')}[/error]")
        return True

    elif cmd == "/session":
        sub = parts[1].lower() if len(parts) > 1 else ""

        if sub == "save":
            path = orchestrator.save_session()
            if path:
                console.print(f"[info]✓ Session saved: {path}[/info]")
            else:
                console.print("[error]Failed to save session.[/error]")
            return True

        elif sub == "list":
            sessions = orchestrator.list_sessions()
            if not sessions:
                console.print("[info]No saved sessions.[/info]")
            else:
                t = Table("N", "Session ID", "Size", box=box.SIMPLE, border_style="dim")
                for i, s in enumerate(sessions[:20], 1):
                    size = f"{s.stat().st_size:,} B"
                    t.add_row(str(i), s.stem, size)
                console.print(t)
            return True

        elif sub == "load" and len(parts) >= 3:
            try:
                n = int(parts[2]) - 1
                sessions = orchestrator.list_sessions()
                if 0 <= n < len(sessions):
                    ok = orchestrator.load_session(sessions[n])
                    if ok:
                        console.print(f"[info]✓ Loaded session: {sessions[n].stem}[/info]")
                    else:
                        console.print("[error]Failed to load session.[/error]")
                else:
                    console.print("[error]Invalid session number.[/error]")
            except ValueError:
                console.print("[error]Usage: /session load <number>[/error]")
            return True

    return False


# ---------------------------------------------------------------------------
# Input prompt styling
# ---------------------------------------------------------------------------

def get_prompt_style() -> Style:
    return Style.from_dict({
        "prompt": "#00ff88 bold",
        "prompt.arrow": "#00ccff",
    })


def get_bottom_toolbar(orchestrator: Optional[Orchestrator]) -> str:
    if orchestrator is None:
        return ""
    usage = orchestrator.token_usage
    pct = usage["usage_pct"]
    color = "ansigreen" if pct < 60 else "ansiyellow" if pct < 85 else "ansired"
    return HTML(
        f'<style fg="ansicyan"> ⚡ ANTIGRAVITY</style>'
        f' <style fg="ansigray">|</style>'
        f' <style fg="ansiblue">{orchestrator.cwd}</style>'
        f' <style fg="ansigray">|</style>'
        f' <style fg="ansigray">ctx </style>'
        f'<style fg="{color}">{pct}%</style>'
        f' <style fg="ansigray">|</style>'
        f' <style fg="ansigray">{orchestrator.model}</style>'
    )


# ---------------------------------------------------------------------------
# Main chat loop
# ---------------------------------------------------------------------------

async def chat_loop(orchestrator: Orchestrator, config) -> None:
    """Main interactive chat loop."""

    # Setup prompt_toolkit session with history file
    history_dir = Path("~/.antigravity").expanduser()
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / "history.txt"

    session: PromptSession = PromptSession(
        history=FileHistory(str(history_file)),
        style=get_prompt_style(),
        bottom_toolbar=lambda: get_bottom_toolbar(orchestrator),
        refresh_interval=1.0,
        mouse_support=False,
    )

    console.print(Rule(style="dim cyan"))
    print_startup_info(orchestrator)

    while True:
        try:
            # Get user input
            try:
                user_input = await session.prompt_async(
                    HTML('<style fg="#00ff88" bold="">❯ </style>'),
                )
            except EOFError:
                # Ctrl+D
                console.print("\n[dim]Goodbye.[/dim]")
                orchestrator.save_session()
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Handle slash commands
            if user_input.startswith("/"):
                try:
                    handled = await handle_slash_command(user_input, orchestrator)
                    if handled:
                        continue
                    else:
                        console.print(f"[error]Unknown command: {user_input}. Type /help for help.[/error]")
                        continue
                except SystemExit:
                    console.print("\n[dim]Goodbye.[/dim]")
                    orchestrator.save_session()
                    break

            # Print agent label
            console.print(f"\n[bold cyan]⚡ Antigravity[/bold cyan] [dim]›[/dim]", end=" ")

            # Run agent turn and handle events
            full_response_parts = []
            pending_confirmation: Optional[ConfirmationRequiredEvent] = None
            streaming_text = ""

            async for event in orchestrator.run_turn(user_input):

                if isinstance(event, TextTokenEvent):
                    # Stream text directly to terminal
                    console.print(event.token, end="", highlight=False)
                    streaming_text += event.token

                elif isinstance(event, ToolStartEvent):
                    # Finish any streaming text with newline
                    if streaming_text.strip():
                        console.print()  # newline after streamed text
                        streaming_text = ""
                    print_tool_start(event.call.tool, event.call.args)

                elif isinstance(event, ToolResultEvent):
                    if config.display.show_tool_calls:
                        print_tool_result(event.call.tool, event.result)
                    full_response_parts.append(
                        f"[Tool: {event.call.tool}] → {event.result[:200]}"
                    )
                    # Reset streaming text for next LLM iteration
                    streaming_text = ""

                elif isinstance(event, ConfirmationRequiredEvent):
                    console.print()
                    console.print(Panel(
                        f"[yellow]{event.prompt}[/yellow]",
                        border_style="yellow",
                        title="[yellow]⚠ Confirmation Required[/yellow]",
                    ))
                    try:
                        answer = await session.prompt_async(
                            HTML('<style fg="#ffaa00">  Confirm [y/N]: </style>')
                        )
                        orchestrator.confirm_tool(answer.strip().lower() == "y")
                    except (EOFError, KeyboardInterrupt):
                        orchestrator.confirm_tool(False)

                elif isinstance(event, ErrorEvent):
                    console.print()
                    print_error(event.message)

                elif isinstance(event, DoneEvent):
                    if streaming_text.strip():
                        console.print()  # Final newline

            console.print()

        except KeyboardInterrupt:
            console.print("\n[dim](Interrupted — Ctrl+D to exit)[/dim]")
            continue

        except Exception as e:
            print_error(f"Unexpected error: {e}")
            import traceback
            console.print(f"[dim]{traceback.format_exc()}[/dim]")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

@click.command()
@click.option("--version", "-v", is_flag=True, help="Show version and exit.")
@click.option("--check", "-c", is_flag=True, help="Check Ollama connection and exit.")
@click.option("--session", "-s", type=str, default=None, help="Load a session file to resume.")
@click.option("--model", "-m", type=str, default=None, help="Override model name.")
@click.option("--host", "-H", type=str, default=None, help="Override Ollama host URL.")
@click.option("--compact", is_flag=True, help="Show compact banner.")
def main(
    version: bool,
    check: bool,
    session: Optional[str],
    model: Optional[str],
    host: Optional[str],
    compact: bool,
) -> None:
    """
    ⚡ Antigravity — Local-first AI Coding Agent

    An intelligent terminal assistant powered by local Ollama models.
    Capable of reasoning, writing code, and executing system commands.

    \b
    Examples:
      ag                         Start interactive session
      ag --check                 Verify Ollama connection
      ag --model qwen2.5-coder:7b  Use a specific model
      ag --session session_xyz   Resume a saved session
    """
    if version:
        click.echo(f"Antigravity CLI v{__version__}")
        return

    # Load config
    config = load_config()

    # CLI overrides
    if model:
        config.ollama.model = model
    if host:
        config.ollama.host = host

    # Print banner
    print_banner(compact=compact)

    if check:
        async def _check():
            from antigravity.llm.client import OllamaClient
            client = OllamaClient(config)
            with console.status("[cyan]Checking connection...[/cyan]"):
                result = await client.health_check()
            if result["ok"]:
                console.print(f"[green]✓ Ollama at {config.ollama.host} is reachable.[/green]")
                models = result.get("models", [])
                if models:
                    console.print("[dim]Models: " + ", ".join(models) + "[/dim]")
            else:
                console.print(f"[error]✗ {result.get('error')}[/error]")
                sys.exit(1)
        asyncio.run(_check())
        return

    # Build orchestrator
    orchestrator = Orchestrator(config=config)

    # Resume session if requested
    if session:
        session_path = Path(session)
        if not session_path.exists():
            # Try looking in session dir
            session_path = config.session_dir / session
        if orchestrator.load_session(session_path):
            console.print(f"[info]✓ Resumed session: {session_path.stem}[/info]")
        else:
            console.print(f"[error]Could not load session: {session}[/error]")

    # Start chat
    try:
        asyncio.run(chat_loop(orchestrator, config))
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye.[/dim]")
        orchestrator.save_session()


if __name__ == "__main__":
    main()
