# Harness Agent

A minimal but complete **Harness Engineering** agent built with LangChain + LangGraph.  
Point it at any local repository and it becomes a persistent, conversational expert on that codebase — answering questions, explaining patterns, and generating structured analysis reports.

---

## What is Harness Engineering?

Harness Engineering means wrapping an LLM core with a set of capabilities so it can act as a reliable, long-lived assistant:

| Layer | What it does |
|-------|-------------|
| **Model (Multi-LLM)** | Pluggable providers: Azure OpenAI, Claude, OpenAI, Gemini — with retry on transient errors |
| **Tools** | `ls`, `read_file`, `glob`, `grep`, `write_file`, `edit_file` — full filesystem access |
| **Memory** | Persists user preferences and per-repo findings across sessions via Markdown files |
| **Context (Compact)** | Auto-summarises old conversation turns when the context window gets full |
| **Permission (HITL)** | Pauses before writing files; approval scope is configurable — one approval per session (default), or re-confirm every call with `--approval-scope call` |
| **Orchestration** | LangGraph state machine driving the agent↔tools control loop |
| **Interaction** *(extension)* | `ask_user` tool — the agent can pause and ask a clarifying question instead of guessing |
| **Feedback** *(extension)* | Skippable 👍/👎 prompt after any turn that actually did something, logged to `memory/feedback.log` |

See [`docs/SPEC.md`](docs/SPEC.md) for the normative contract (interfaces,
error taxonomy, config parameters, invariants, and failure modes) of each layer.

---

## Project Structure

```
harness-agent-poc/
├── harness_agent/
│   ├── agent.py              # LangGraph graph — state, nodes, middleware wiring
│   ├── main.py               # CLI (click) — chat, analyze, config commands
│   ├── tools/
│   │   └── filesystem.py     # ls, read_file, glob, grep, write_file, edit_file
│   ├── middleware/
│   │   ├── base.py           # AgentMiddleware base class
│   │   ├── memory.py         # Load/inject AGENTS.md + per-repo memory
│   │   ├── compact.py        # Auto-compress context when token count is high
│   │   └── hitl.py           # Human-in-the-loop approval UI (Rich)
│   ├── llm/
│   │   └── providers.py      # Azure / Claude / OpenAI / Gemini factory
│   └── prompts/
│       └── system.md         # Base system prompt
├── memory/
│   ├── AGENTS.md             # Global user preferences (editable, version-controlled)
│   └── repos/
│       └── {repo-name}.md    # Per-repo analysis history
├── reports/
│   └── {repo-name}/
│       ├── 01_architecture.md
│       ├── 02_components.md
│       └── 03_takeaways.md
└── pyproject.toml            # uv-managed dependencies
```

---

## Setup

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
# Clone and install
git clone https://github.com/yujun/harness-agent-poc
cd harness-agent-poc
uv sync

# Configure your API key
cp .env.example .env
# Edit .env and fill in your provider credentials
```

### `.env` example

```env
# Azure OpenAI (auto-detected if AZURE_OPENAI_API_KEY is set)
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_DEPLOYMENT=gpt-4.1
AZURE_OPENAI_API_KEY=<your-key>

# Or Anthropic Claude
ANTHROPIC_API_KEY=<your-key>
```

The default provider is auto-detected: if `AZURE_OPENAI_API_KEY` is present it uses Azure, otherwise falls back to Claude.  
Override at any time with `--model claude|openai|azure|gemini`.

---

## Usage

### `chat` — conversational mode

Start an interactive session about a repo. If previous analysis reports exist, they are loaded automatically as context.

```bash
uv run harness-agent chat <repo-name>
```

The agent searches common locations (`~/Documents/GitHub`, `~/code`, etc.) for the repo by name, confirms the path with you, then opens a REPL.

### `analyze` — generate structured reports

Run a full analysis and write Markdown reports to `reports/<repo-name>/`.  
If reports already exist, you are asked whether to overwrite or open chat instead.

```bash
uv run harness-agent analyze <repo-name>
```

You can choose which dimensions to produce:

```
  #  Dimension     Description
  1  Architecture  High-level design, layers, data flow, tech stack
  2  Components    Key modules, responsibilities, interactions
  3  Takeaways     Nice patterns, clever decisions, lessons learned

Choice [1 2 3]: 1 3   ← architecture + takeaways only
```

After the reports are written, the session continues as a chat.

### `config` — show current settings

```bash
uv run harness-agent config
```

---

## Demo

### Memory — the agent learns your preferences

```
You: 你叫做大哥
→ edit_file(memory/AGENTS.md)   ← updates memory before replying

已記錄你的偏好，從現在開始我的名字是「大哥」。

You: 你叫什麼名字
我的名字是「大哥」，這是你剛才自己幫我取的。
```

The agent writes preferences to `memory/AGENTS.md` immediately and carries them across sessions.

---

### Existing reports loaded automatically

```
$ uv run harness-agent chat deepagents

Loaded existing reports:
  reports/deepagents/01_architecture.md
  reports/deepagents/02_components.md
  reports/deepagents/03_takeaways.md

You: 可以稍微介紹這個 project 的架構嗎

DeepAgents 是一個 AI Agent 框架，主要基於 LangChain 和 LangGraph，
提供可擴展的 middleware 層，支援記憶、HITL、context 壓縮等功能...
```

No re-analysis needed — the agent answers from the cached reports.

---

### HITL — one approval covers the whole session

```
╭──────────── Approval Required ────────────╮
│ Agent wants to write files                │
│ Review the operations below before        │
│ approving.                                │
╰───────────────────────────────────────────╯

1. write_file
   Path: reports/deepagents/01_architecture.md
   # DeepAgents: High-Level Architecture ...

Approve all? (yes / no): yes
```

Approve once → all subsequent `write_file` calls in the session run automatically.

---

## Observable Memory Files

All memory is stored as plain Markdown inside the project — open them in any editor:

```
memory/
├── AGENTS.md             ← your global preferences
└── repos/
    └── deepagents.md     ← findings from each analysed repo
```

The agent updates these files using `edit_file` (targeted string replacement) so changes are minimal and diff-friendly.
