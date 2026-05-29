# ⚡ Antigravity CLI

> Local-first AI Coding Agent powered by Ollama · No cloud required · Full system access

```
⚡ ANTIGRAVITY  v0.1.0
Local-first AI Coding Agent powered by Ollama
```

---

## Features

- 🤖 **ReAct Agent Loop** — Reason → Act → Observe, multi-step tool execution
- 🛠️ **System Tools** — Shell commands, file read/write/patch, directory navigation
- 📡 **Local-first** — Runs entirely on your network via Ollama (no OpenAI/cloud required)
- 💾 **Session Persistence** — Save and resume conversations
- 🎨 **Rich Terminal UI** — Syntax highlighting, markdown rendering, live streaming
- 🔒 **Safe by Default** — Dangerous command confirmation prompts
- ⚙️ **Configurable** — YAML config, env var overrides, CLI flags

---

## Requirements

- Python 3.11+
- Ollama server accessible on your network
- Linux (tested on Kali Linux)

---

## Installation

### 1. Clone / navigate to the project

```bash
cd "IA Local Agente"
```

### 2. Create a virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -e .
```

This installs `ag` and `antigravity` as CLI commands.

### 4. Configure

```bash
mkdir -p ~/.antigravity
cp config.example.yaml ~/.antigravity/config.yaml
# Edit the config if needed:
nano ~/.antigravity/config.yaml
```

By default, Antigravity connects to `http://192.168.1.136:11434/v1` using `llama3.1:8b`.

---

## Usage

```bash
# Start interactive agent
ag

# Check Ollama connection
ag --check

# Use a different model
ag --model qwen2.5-coder:7b

# Use a different Ollama server
ag --host http://192.168.1.200:11434/v1

# Resume a saved session
ag --session session_20240529_180000

# Compact mode (smaller banner)
ag --compact
```

---

## In-Session Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/clear` | Clear conversation history |
| `/tokens` | Show context token usage |
| `/cwd` | Show current working directory |
| `/cd <path>` | Change working directory |
| `/model` | Show model info |
| `/check` | Check Ollama connection |
| `/session save` | Save current session |
| `/session list` | List saved sessions |
| `/session load <N>` | Load session N from the list |
| `/exit` or `/quit` | Exit (also saves session) |

Press **Ctrl+D** to exit (saves session automatically).
Press **Ctrl+C** to interrupt a running command.

---

## Tool System

The agent uses a structured `<tool_call>` protocol — no native function calling needed:

```
<tool_call>
{"tool": "shell", "args": {"command": "ls -la"}}
</tool_call>
```

### Available Tools

| Tool | Description |
|------|-------------|
| `shell` | Execute bash commands |
| `read_file` | Read file contents |
| `write_file` | Create/overwrite files |
| `patch_file` | Replace exact text in files |
| `list_dir` | List directory contents |
| `get_cwd` | Get working directory |
| `set_cwd` | Change working directory |
| `find_files` | Recursive file search by glob |

---

## Configuration

Config file: `~/.antigravity/config.yaml`

```yaml
ollama:
  host: "http://192.168.1.136:11434/v1"
  model: "llama3.1:8b"
  context_size: 8192
  temperature: 0.1
  timeout: 120

agent:
  max_tool_iterations: 10
  dangerous_commands_require_confirm: true

display:
  theme: "monokai"       # monokai, dracula, nord, github-dark
  show_tool_calls: true
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTIGRAVITY_OLLAMA_HOST` | Override Ollama server URL |
| `ANTIGRAVITY_MODEL` | Override model name |

---

## Architecture

```
User Input
    │
    ▼
┌─────────────────────────────────────────┐
│              CLI (cli.py)               │  Rich + prompt_toolkit
│  - Streaming display                    │
│  - Slash commands                       │
│  - Session management                   │
└────────────────┬────────────────────────┘
                 │ events
    ▼
┌─────────────────────────────────────────┐
│         Orchestrator (ReAct Loop)       │  orchestrator.py
│  - Tool call detection & parsing        │
│  - Multi-iteration tool loop            │
│  - Dangerous command gating             │
│  - Session persistence                  │
└──────┬───────────────────┬─────────────┘
       │                   │
       ▼                   ▼
┌──────────────┐   ┌──────────────────────┐
│  LLM Client  │   │    Tool Registry     │
│  (httpx SSE) │   │  shell / fs / nav    │
│              │   │                      │
│  Ollama /v1  │   │  Context Manager     │
│  192.168.x.x │   │  (sliding window)    │
└──────────────┘   └──────────────────────┘
```

---

## Project Structure

```
IA Local Agente/
├── antigravity/
│   ├── __init__.py
│   ├── cli.py              # Terminal interface
│   ├── orchestrator.py     # Core ReAct agent loop
│   ├── config.py           # Configuration management
│   ├── llm/
│   │   ├── client.py       # Ollama HTTP client (SSE streaming)
│   │   └── context.py      # Context/memory management
│   └── tools/
│       ├── registry.py     # Tool dispatcher + system prompt builder
│       ├── shell.py        # Shell command execution
│       ├── filesystem.py   # File operations
│       └── navigator.py    # Directory navigation
├── pyproject.toml
├── config.example.yaml
└── README.md
```

---

## License

MIT © Antigravity Project
