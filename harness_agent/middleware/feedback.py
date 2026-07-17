"""Post-turn feedback: an optional, skippable rating collected after actioned turns.

This is an extension beyond the base six-layer harness architecture (Model,
Tools, Memory, Context, Permission, Orchestration) — see docs/SPEC.md §7.

Contract
--------
`maybe_prompt_feedback()` fires only after a turn in which the agent
actually executed at least one tool call (a proxy for "completed a task",
as opposed to a purely conversational reply that answered a question with
no side effects). `ask_user` calls do not count on their own — asking a
question isn't a completed task — so a turn that only clarified something
does not trigger a rating prompt.

The prompt is always skippable: pressing Enter with no input records
nothing and returns immediately. Any input that isn't recognised as
good/bad is also treated as a skip, never an error — a malformed answer
must never block the next turn.

Storage: append-only JSONL at memory/feedback.log, one record per
non-skipped rating: {timestamp, repo, tool_calls_this_turn, rating, comment}.
Failure to write is non-fatal, matching the audit log's contract in
middleware/hitl.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

console = Console()

_PROJECT_ROOT = Path(__file__).parent.parent.parent
FEEDBACK_LOG_FILE = _PROJECT_ROOT / "memory" / "feedback.log"

_RATING_ALIASES = {"g": "good", "good": "good", "b": "bad", "bad": "bad"}


def maybe_prompt_feedback(repo_name: str, tool_names_this_turn: list[str]) -> None:
    """Show a skippable rating prompt after a turn that executed >=1 tool call."""
    if not tool_names_this_turn:
        return  # pure conversational turn — do not interrupt with a rating ask

    console.print(
        "\n[dim]How was that? "
        "([green]g[/green]ood / [red]b[/red]ad / Enter to skip)[/dim]",
        end=" ",
    )
    choice = console.input().strip().lower()
    if not choice:
        return  # skipped — no record written, no further friction

    rating = _RATING_ALIASES.get(choice)
    if rating is None:
        return  # unrecognised input is a skip, not an error

    comment = ""
    if rating == "bad":
        comment = console.input("[dim]What went wrong (optional): [/dim]").strip()

    _log_feedback(repo_name, tool_names_this_turn, rating, comment)


def _log_feedback(repo_name: str, tool_names: list[str], rating: str, comment: str) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repo": repo_name,
        "tool_calls_this_turn": tool_names,
        "rating": rating,
        "comment": comment,
    }
    try:
        FEEDBACK_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        console.print(f"[dim red]Warning: could not write feedback log: {e}[/dim red]")
