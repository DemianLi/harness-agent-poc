"""Human-in-the-loop middleware: pauses before high-risk tool calls for approval.

Permission contract
--------------------
- Risk classification is defined once, in `tools/filesystem.py::HIGH_RISK_TOOLS`
  (see that module's docstring for the classification rationale). This module
  does not re-derive risk; it only renders the approval prompt and records
  the decision.
- Approval scope: `request_approval()` is called with ALL risky tool calls
  from a single agent turn as one batch; the human's decision (yes/no)
  applies to the entire batch atomically — there is no partial approval.
- Approval durability: the decision itself does not persist here. The caller
  (`agent.py`) is responsible for applying the `approval_scope` setting
  below to the session-level `writes_approved` flag; this module only
  renders the prompt and appends an immutable audit record.
- Audit trail: every decision (approved or rejected) MUST be appended to the
  audit log via `log_decision()` before the tool calls are executed. The log
  is append-only, one JSON object per line (JSONL), and is never mutated or
  truncated by this module.

Approval scope configuration
------------------------------
`HARNESS_APPROVAL_SCOPE` (env var) or the `--approval-scope` CLI flag
selects how long an approval lasts, resolved by `resolve_approval_scope()`:

- `"session"` (default) — approving one batch of high-risk calls sets
  `writes_approved = True` for the rest of the thread; subsequent high-risk
  calls in the same session are NOT re-prompted. This is the original
  behaviour, kept as the default for backward compatibility.
- `"call"` — every batch of high-risk calls is prompted, regardless of
  prior approvals in the same thread. Use this when "must ask every time"
  is a hard requirement rather than a one-time session grant.

An unrecognised value (bad env var) falls back to `"session"` rather than
raising, since this is a runtime environment setting, not a startup
precondition; an unrecognised `--approval-scope` CLI value is rejected
up front by `click.Choice` instead (fail fast on operator typos).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()

_PROJECT_ROOT = Path(__file__).parent.parent.parent
AUDIT_LOG_DIR = _PROJECT_ROOT / "memory"
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit.log"

VALID_APPROVAL_SCOPES = ("session", "call")


def resolve_approval_scope(override: str | None = None) -> str:
    """Resolve the approval scope: explicit override > env var > "session" default."""
    candidate = (override or os.getenv("HARNESS_APPROVAL_SCOPE") or "session").strip().lower()
    return candidate if candidate in VALID_APPROVAL_SCOPES else "session"


def request_approval(tool_calls: list[dict[str, Any]]) -> bool:
    """Display pending tool calls and ask the user to approve or reject.

    All tool calls are shown at once; one decision covers all of them.
    Returns True if approved, False if rejected.
    """
    console.print()
    console.print(Panel.fit(
        "[bold yellow]Agent wants to write files[/bold yellow]\n"
        "Review the operations below before approving.",
        title="[bold]Approval Required[/bold]",
        border_style="yellow",
    ))

    for i, tc in enumerate(tool_calls, 1):
        name = tc.get("name", "unknown")
        args = tc.get("args", {})

        console.print(f"\n[bold cyan]{i}. {name}[/bold cyan]")

        if "file_path" in args:
            console.print(f"   Path: [green]{args['file_path']}[/green]")

        if "content" in args:
            preview = args["content"][:500]
            if len(args["content"]) > 500:
                preview += "\n... (truncated)"
            console.print(Syntax(preview, "markdown", theme="monokai", line_numbers=False))

    console.print()
    while True:
        choice = console.input(
            "[bold]Approve all? ([green]y[/green]es / [red]n[/red]o)[/bold]: "
        ).strip().lower()
        if choice in ("y", "yes"):
            return True
        if choice in ("n", "no"):
            return False
        console.print("[dim]Please enter y or n.[/dim]")


def log_decision(repo_name: str, tool_calls: list[dict[str, Any]], approved: bool) -> None:
    """Append an immutable audit record for a batch approval decision.

    Contract: one JSON line per decision, never overwritten or removed.
    Failure to write the audit log is non-fatal (a missing/unwritable
    memory dir must not block the agent turn) — it is logged to stderr
    via console instead.
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repo": repo_name,
        "approved": approved,
        "tool_calls": [
            {"name": tc.get("name"), "args": tc.get("args", {})} for tc in tool_calls
        ],
    }
    try:
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        console.print(f"[dim red]Warning: could not write audit log: {e}[/dim red]")
