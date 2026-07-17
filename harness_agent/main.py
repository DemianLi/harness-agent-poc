"""CLI entry point for the Harness Agent."""

from __future__ import annotations

from pathlib import Path

import click
from langchain_core.messages import AIMessage, HumanMessage
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from .agent import build_graph
from .llm.providers import create_llm, ensure_config_exists
from .middleware.feedback import maybe_prompt_feedback
from .middleware.hitl import VALID_APPROVAL_SCOPES
from .middleware.memory import GLOBAL_MEMORY_FILE, MEMORY_DIR, REPO_MEMORY_DIR, ensure_memory_files

console = Console()

PROVIDERS = ["claude", "openai", "azure", "gemini"]

SEARCH_ROOTS = [
    Path.home() / "Documents" / "GitHub",
    Path.home() / "code",
    Path.home() / "projects",
    Path.home() / "dev",
    Path.home() / "src",
    Path.home(),
]

DIMENSIONS: dict[str, tuple[str, str, str]] = {
    "1": ("01_architecture.md", "Architecture", "High-level design, layers, data flow, tech stack"),
    "2": ("02_components.md",   "Components",   "Key modules, responsibilities, interactions"),
    "3": ("03_takeaways.md",    "Takeaways",    "Nice patterns, clever decisions, lessons learned"),
}

# Paths inside this project that should never be treated as external repos
_PROJECT_ROOT = Path(__file__).parent.parent
_EXCLUDED_ROOTS = {
    (_PROJECT_ROOT / "reports").resolve(),
    (_PROJECT_ROOT / "memory").resolve(),
}


# --------------------------------------------------------------------------- #
# CLI commands                                                                 #
# --------------------------------------------------------------------------- #

@click.group()
def cli() -> None:
    """Harness Agent — a conversational repo assistant powered by LangGraph."""


@cli.command()
@click.argument("repo_name")
@click.option("--model", type=click.Choice(PROVIDERS), default=None,
              help="LLM provider (overrides config default).")
@click.option("--approval-scope", type=click.Choice(VALID_APPROVAL_SCOPES), default=None,
              help="'session' (default): approve write_file once per session. "
                   "'call': re-prompt every time. Overrides HARNESS_APPROVAL_SCOPE.")
def chat(repo_name: str, model: str | None, approval_scope: str | None) -> None:
    """Start an interactive chat session about a repository.

    REPO_NAME is the directory name of the repository to load.
    If previous analysis reports exist, they are loaded as context automatically.
    Type 'exit' or press Ctrl+C to quit.
    """
    repo, llm, app, config = _setup_session(repo_name, model, approval_scope)
    if repo is None:
        return

    console.print(f"\n[bold green]Harness Agent[/bold green] — chatting about "
                  f"[cyan]{repo.name}[/cyan]")
    console.print(f"[dim]Path:     {repo}[/dim]")
    console.print(f"[dim]Memory:   {GLOBAL_MEMORY_FILE}[/dim]")
    console.print(f"[dim]Repo mem: {REPO_MEMORY_DIR}/{repo.name}.md[/dim]")
    console.print("[dim]Type 'exit' to quit.[/dim]\n")

    existing = _load_existing_reports(repo.name)

    if existing:
        # Show which reports are loaded
        console.print("[dim]Loaded existing reports:[/dim]")
        for name in existing:
            console.print(f"[dim]  reports/{repo.name}/{name}[/dim]")
        console.print()

        reports_block = "\n\n".join(
            f"### {name}\n{content}" for name, content in existing.items()
        )
        first_message = (
            f"Repository: {repo} (name: '{repo.name}')\n\n"
            f"I have loaded the following existing analysis reports as context:\n\n"
            f"{reports_block}\n\n"
            f"Use these reports to answer questions. "
            f"Only explore the filesystem if the question goes beyond what the reports cover. "
            f"If asked to re-analyse, do a fresh analysis and overwrite the reports."
        )
    else:
        first_message = (
            f"Repository: {repo} (name: '{repo.name}')\n\n"
            f"No previous analysis reports found. "
            f"I'm ready to answer questions or run an analysis — what would you like?"
        )

    _repl(app, _make_initial_state(first_message), config, repo_name=repo.name)


@cli.command()
@click.argument("repo_name")
@click.option("--model", type=click.Choice(PROVIDERS), default=None,
              help="LLM provider (overrides config default).")
@click.option("--approval-scope", type=click.Choice(VALID_APPROVAL_SCOPES), default=None,
              help="'session' (default): approve write_file once per session. "
                   "'call': re-prompt every time. Overrides HARNESS_APPROVAL_SCOPE.")
def analyze(repo_name: str, model: str | None, approval_scope: str | None) -> None:
    """Run a structured analysis of a repository, then stay in chat.

    REPO_NAME is the directory name of the repository to analyse.
    After the analysis is written, you can continue asking questions.
    """
    repo, llm, app, config = _setup_session(repo_name, model, approval_scope)
    if repo is None:
        return

    # Warn if reports already exist
    existing = _load_existing_reports(repo.name)
    if existing:
        console.print("[yellow]Existing reports found:[/yellow]")
        for name in existing:
            console.print(f"[dim]  reports/{repo.name}/{name}[/dim]")
        console.print()
        confirm = console.input(
            "Re-analyse and overwrite? ([green]y[/green]es / [red]n[/red]o, open chat instead): "
        ).strip().lower()
        if confirm not in ("y", "yes"):
            console.print("[dim]Opening chat with existing reports instead.[/dim]")
            # Delegate to chat flow
            _chat_with_reports(repo, existing, app, config)
            return

    # Dimension selection
    selected = _select_dimensions()
    if not selected:
        console.print("[yellow]Cancelled.[/yellow]")
        return

    console.print(f"\n[bold green]Harness Agent[/bold green] — analysing "
                  f"[cyan]{repo.name}[/cyan]")
    console.print(f"[dim]Path:     {repo}[/dim]")
    console.print(f"[dim]Memory:   {GLOBAL_MEMORY_FILE}[/dim]")
    console.print(f"[dim]Repo mem: {REPO_MEMORY_DIR}/{repo.name}.md[/dim]")
    console.print("[dim]Type 'exit' to quit after analysis.[/dim]\n")

    report_lines = "\n".join(
        f"  - reports/{repo.name}/{file}" for file, _, _ in selected
    )
    dimension_labels = ", ".join(label for _, label, _ in selected)

    initial_state = _make_initial_state(
        f"Please analyse the repository at: {repo}\n\n"
        f"Repo name: '{repo.name}'. Focus on: {dimension_labels}.\n\n"
        f"Write the reports to:\n{report_lines}\n\n"
        f"Start by exploring the structure, then read key files. "
        f"Ask me if anything is ambiguous."
    )
    _repl(app, initial_state, config, repo_name=repo.name)


# --------------------------------------------------------------------------- #
# Report helpers                                                               #
# --------------------------------------------------------------------------- #

def _load_existing_reports(repo_name: str) -> dict[str, str]:
    """Return a dict of {filename: content} for any existing reports."""
    reports_dir = Path(__file__).parent.parent / "reports" / repo_name
    if not reports_dir.exists():
        return {}
    result = {}
    for f in sorted(reports_dir.glob("*.md")):
        result[f.name] = f.read_text(encoding="utf-8")
    return result


def _chat_with_reports(repo: Path, existing: dict[str, str], app: any, config: dict) -> None:
    """Start a chat session pre-loaded with existing report content."""
    console.print(f"\n[bold green]Harness Agent[/bold green] — chatting about "
                  f"[cyan]{repo.name}[/cyan]")
    console.print("[dim]Type 'exit' to quit.[/dim]\n")

    reports_block = "\n\n".join(
        f"### {name}\n{content}" for name, content in existing.items()
    )
    first_message = (
        f"Repository: {repo} (name: '{repo.name}')\n\n"
        f"I have loaded the following existing analysis reports as context:\n\n"
        f"{reports_block}\n\n"
        f"Use these reports to answer questions. "
        f"Only explore the filesystem if the question goes beyond what the reports cover."
    )
    _repl(app, _make_initial_state(first_message), config, repo_name=repo.name)


# --------------------------------------------------------------------------- #
# Shared setup                                                                 #
# --------------------------------------------------------------------------- #

def _setup_session(repo_name: str, model: str | None, approval_scope: str | None = None):
    """Find repo, confirm with user, build agent. Returns (repo, llm, app, config) or Nones."""
    matches = _find_repos(repo_name)
    if not matches:
        console.print(f"[red]No repository found matching '{repo_name}'.[/red]")
        for root in SEARCH_ROOTS:
            console.print(f"[dim]  {root}[/dim]")
        return None, None, None, None

    repo = _confirm_repo(matches, repo_name)
    if repo is None:
        console.print("[yellow]Cancelled.[/yellow]")
        return None, None, None, None

    ensure_config_exists()
    ensure_memory_files(repo.name)

    llm = create_llm(provider=model)
    app = build_graph(llm=llm, repo_name=repo.name, approval_scope=approval_scope)
    config = {"configurable": {"thread_id": f"chat-{repo.name}"}}
    return repo, llm, app, config


def _make_initial_state(first_message: str) -> dict:
    return {
        "messages": [HumanMessage(content=first_message)],
        "memory_loaded": False,
        "global_memory": "",
        "repo_memory": "",
        "writes_approved": False,
    }


# --------------------------------------------------------------------------- #
# REPL loop                                                                    #
# --------------------------------------------------------------------------- #

def _repl(app: any, initial_state: dict, config: dict, repo_name: str) -> None:
    """Main conversation loop. Runs until the user types 'exit' or presses Ctrl+C."""
    current_input = initial_state

    try:
        while True:
            # Stream agent response
            tool_names = _stream_response(app, current_input, config)

            # Ask for a quick, skippable rating after a turn that actually
            # did something (see middleware/feedback.py's contract) — a
            # pure conversational reply does not trigger this.
            maybe_prompt_feedback(repo_name, tool_names)

            # Prompt for next input
            console.print()
            try:
                user_input = console.input("[bold cyan]You:[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if user_input.lower() in ("exit", "quit", "q", "bye"):
                break
            if not user_input:
                continue

            current_input = {"messages": [HumanMessage(content=user_input)]}

    except KeyboardInterrupt:
        pass

    console.print("\n[dim]Session ended.[/dim]")
    _print_report_locations(repo_name)


def _stream_response(app: any, input_state: dict, config: dict) -> list[str]:
    """Stream one agent turn to the console.

    Returns the names of tools actually invoked this turn (excluding
    `ask_user`, which is a clarification, not a completed action) — used by
    `_repl` to decide whether to show the post-turn feedback prompt.
    """
    tool_names: list[str] = []
    for event in app.stream(input_state, config, stream_mode="values"):
        messages = event.get("messages", [])
        if not messages:
            continue
        last = messages[-1]
        if isinstance(last, AIMessage):
            if last.content and not last.tool_calls:
                console.print()
                console.print(Markdown(str(last.content)))
            elif last.tool_calls:
                for tc in last.tool_calls:
                    preview = _format_args_preview(tc.get("args", {}))
                    console.print(f"[dim]→ {tc['name']}({preview})[/dim]")
                    if tc["name"] != "ask_user":
                        tool_names.append(tc["name"])
    return tool_names


# --------------------------------------------------------------------------- #
# Repo discovery                                                               #
# --------------------------------------------------------------------------- #

def _find_repos(name: str) -> list[Path]:
    seen: set[Path] = set()
    found: list[Path] = []
    name_lower = name.lower()

    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for candidate in root.rglob("*"):
            if not candidate.is_dir():
                continue
            if candidate.name.lower() != name_lower:
                continue
            if any(part.startswith(".") for part in candidate.parts[-3:]):
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            # Skip paths inside this project's reports/ or memory/
            if any(resolved.is_relative_to(ex) for ex in _EXCLUDED_ROOTS):
                continue
            # Skip if this path is nested inside an already-found repo
            if any(resolved.is_relative_to(r.resolve()) for r in found):
                continue
            seen.add(resolved)
            found.append(candidate)
            break
        if len(found) >= 5:
            break

    return found


def _confirm_repo(matches: list[Path], name: str) -> Path | None:
    console.print()

    if len(matches) == 1:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_row("[bold cyan]Found:[/bold cyan]", str(matches[0]))
        console.print(Panel(table, title="[bold yellow]Confirm Repository[/bold yellow]",
                             border_style="yellow"))
        console.print()
        choice = console.input("Is this correct? ([green]y[/green]es / [red]n[/red]o): ").strip().lower()
        return matches[0] if choice in ("y", "yes") else None

    table = Table(title=f"Found {len(matches)} matches for '{name}'", box=None)
    table.add_column("#", style="bold cyan", width=4)
    table.add_column("Path")
    for i, path in enumerate(matches, 1):
        table.add_row(str(i), str(path))
    console.print(table)
    console.print()

    while True:
        raw = console.input(
            f"Select [bold cyan]1–{len(matches)}[/bold cyan] or [red]q[/red] to quit: "
        ).strip().lower()
        if raw == "q":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(matches):
            return matches[int(raw) - 1]
        console.print("[dim]Invalid choice, try again.[/dim]")


# --------------------------------------------------------------------------- #
# Dimension selection                                                          #
# --------------------------------------------------------------------------- #

def _select_dimensions() -> list[tuple[str, str, str]]:
    console.print()
    table = Table(title="Select analysis dimensions", box=None)
    table.add_column("#", style="bold cyan", width=4)
    table.add_column("Dimension", style="bold")
    table.add_column("Description", style="dim")
    for key, (_, label, desc) in DIMENSIONS.items():
        table.add_row(key, label, desc)
    console.print(table)
    console.print("[dim]Enter numbers separated by spaces, or press Enter for all.[/dim]\n")

    raw = console.input("Choice [1 2 3]: ").strip()
    if not raw:
        return list(DIMENSIONS.values())

    selected = [DIMENSIONS[t] for t in raw.split() if t in DIMENSIONS]
    if not selected:
        console.print("[dim]Defaulting to all dimensions.[/dim]")
        return list(DIMENSIONS.values())
    return selected


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _format_args_preview(args: dict) -> str:
    parts = []
    for k, v in args.items():
        val = str(v)
        if len(val) > 60:
            val = val[:57] + "..."
        parts.append(f"{k}={val!r}")
    return ", ".join(parts)


def _print_report_locations(repo_name: str) -> None:
    reports_dir = Path(__file__).parent.parent / "reports" / repo_name
    if reports_dir.exists():
        files = sorted(reports_dir.glob("*.md"))
        if files:
            console.print(f"[dim]Reports: {reports_dir}[/dim]")
            for f in files:
                console.print(f"[dim]  {f.name}[/dim]")


# --------------------------------------------------------------------------- #
# Config command                                                               #
# --------------------------------------------------------------------------- #

@cli.command()
def config() -> None:
    """Show the current configuration and memory file paths."""
    from .llm.providers import CONFIG_PATH, get_default_provider, load_config
    from .middleware.hitl import resolve_approval_scope

    ensure_config_exists()
    cfg = load_config()

    console.print(f"\n[bold]Config:[/bold]       {CONFIG_PATH}")
    console.print(f"[bold]Provider:[/bold]     {get_default_provider()}")
    console.print(f"[bold]Approval scope:[/bold] {resolve_approval_scope()}")
    console.print(f"[bold]Memory dir:[/bold]   {MEMORY_DIR}")

    if cfg.get("llm", {}).get("model"):
        console.print(f"[bold]Model:[/bold]        {cfg['llm']['model']}")
