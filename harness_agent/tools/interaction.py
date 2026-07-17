"""Interaction tools: a structured clarification request to the human.

Contract
--------
`ask_user` lets the model pause the turn and request clarification instead
of guessing. It is read-only and side-effect-free — it changes no files and
no state — so per the risk classification in `tools/filesystem.py` it is
never a member of `HIGH_RISK_TOOLS` and never requires HITL approval.

It blocks synchronously on console input, the same way
`middleware/hitl.py::request_approval` already blocks the control loop for
approval prompts — consistent with this project's single-user, single-
process CLI execution model (see that module's trust boundary).

Trust boundary — this does not force clarification
-----------------------------------------------------
Nothing prevents the model from answering an ambiguous request without
calling this tool. Making `ask_user` available turns "ask when ambiguous"
from a prose-only convention (previously just a line in
`prompts/system.md`) into an observable, tool-call-shaped action — every
invocation shows up in the same tool-call trace as `read_file`/`write_file`
calls — but it is still the model's judgment call whether to use it. A
hard guarantee ("must always ask before X") requires structural
enforcement in the graph, not a tool the model can choose to skip.
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel

console = Console()


class AskUserInput(BaseModel):
    question: str = Field(description="The clarifying question to ask the user")
    options: list[str] = Field(
        default_factory=list,
        description="Optional short list of suggested answers. The user may still type free text.",
    )


@tool(args_schema=AskUserInput)
def ask_user(question: str, options: list[str] | None = None) -> str:
    """Ask the user a clarifying question and block until they answer.

    Use this when a request is ambiguous enough that guessing could lead to
    an incorrect or unwanted action — especially before a high-risk
    operation like write_file. Do not use it for trivial ambiguity you can
    reasonably resolve yourself; it interrupts the user's flow.
    """
    options = options or []

    console.print()
    console.print(Panel.fit(
        f"[bold]{question}[/bold]",
        title="[bold cyan]Clarification Needed[/bold cyan]",
        border_style="cyan",
    ))
    for i, opt in enumerate(options, 1):
        console.print(f"  [cyan]{i}.[/cyan] {opt}")
    if options:
        console.print("[dim]Type a number to pick one, or type your own answer.[/dim]")

    answer = console.input("\n[bold cyan]Your answer:[/bold cyan] ").strip()

    if answer.isdigit() and 1 <= int(answer) <= len(options):
        answer = options[int(answer) - 1]

    return answer


# Exported list for use in the agent
INTERACTION_TOOLS = [ask_user]
