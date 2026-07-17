"""Memory middleware: loads AGENTS.md and per-repo memory into the system prompt.

Schema contract
---------------
`memory/AGENTS.md` (global) MUST contain, in order:
    # Agent Memory
    ## User Preferences
    ## Notes
`memory/repos/{repo_name}.md` (per-repo) MUST contain, in order:
    # {repo_name}
    ## Previous Analyses
Both headers are load-bearing: the agent's memory-update instructions
(`_MEMORY_GUIDELINES`) target `"## Previous Analyses\n"` as the anchor for
`edit_file` appends. Renaming or removing these headers breaks the append
contract silently (the `edit_file` call will fail with `not_unique`/"not
found" rather than corrupting the file, per the tools error contract).

Preference extraction contract
-------------------------------
`_extract_name_preference` recognises the keys in `_NAME_PREFERENCE_PATTERNS`
(case-insensitive). Lines are scanned in file order and the FIRST matching
line wins — later occurrences of the same key are ignored, not merged. This
is a deliberate simplification: memory files are small and human-curated,
so "first wins" avoids needing conflict-resolution logic and keeps update
order easy to reason about (edits should replace the old line, not append
a second one).

Failure mode
------------
A missing memory file is not an error — `_read_file` returns `""` and the
agent proceeds with no memory context. A malformed file (headers renamed or
removed) degrades to "no preference detected", never a crash.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from .base import AgentMiddleware, append_to_system

# Memory lives inside the project root for easy observation
_PROJECT_ROOT = Path(__file__).parent.parent.parent
MEMORY_DIR = _PROJECT_ROOT / "memory"
GLOBAL_MEMORY_FILE = MEMORY_DIR / "AGENTS.md"
REPO_MEMORY_DIR = MEMORY_DIR / "repos"

_MEMORY_GUIDELINES = """<memory_guidelines>
## When to update memory

**During conversation** — if the user gives feedback or states a preference,
call `edit_file` to update memory BEFORE doing anything else.

Update when:
✓ User states how analyses should be written
✓ User corrects your approach or gives feedback
✓ You discover a pattern that should persist across sessions

Do NOT update for: one-time requests, temporary context, small talk.
NEVER store API keys or credentials.

## After completing an analysis

Once all reports are written, you MUST call `edit_file` to append a summary
to the repo memory file:

  file_path: {repo_memory_path}
  old_string: "## Previous Analyses\n"
  new_string: "## Previous Analyses\n\n### {date}\n{summary}\n"

Keep the summary to 3-5 bullet points covering: tech stack, key patterns found,
and anything notable for future reference.
</memory_guidelines>"""


class MemoryMiddleware(AgentMiddleware):
    """Loads global and repo-specific memory and injects them into the system prompt."""

    def __init__(self, repo_name: str | None = None):
        self.repo_name = repo_name

    def before_agent(self, state: dict[str, Any]) -> dict[str, Any] | None:
        # Only load once per session
        if "memory_loaded" in state:
            return None

        global_memory = _read_file(GLOBAL_MEMORY_FILE)
        repo_memory = _read_file(REPO_MEMORY_DIR / f"{self.repo_name}.md") if self.repo_name else ""

        return {
            "memory_loaded": True,
            "global_memory": global_memory,
            "repo_memory": repo_memory,
        }

    def inject_system(self, system: str, state: dict[str, Any]) -> str:
        global_mem = state.get("global_memory", "")
        repo_mem = state.get("repo_memory", "")

        parts = []

        # If a name preference is stored in memory, prepend it as a hard directive
        # so it takes priority over the default title in the system prompt.
        name = _extract_name_preference(global_mem)
        if name:
            parts.append(f"Your name for this session is: **{name}**. "
                         f"Use this name whenever you introduce yourself.")

        memory_content = ""
        if global_mem:
            memory_content += f"{GLOBAL_MEMORY_FILE}\n{global_mem}\n"
        if repo_mem and self.repo_name:
            memory_content += f"\n{REPO_MEMORY_DIR}/{self.repo_name}.md\n{repo_mem}"

        if memory_content:
            parts.append(f"<agent_memory>\n{memory_content.strip()}\n</agent_memory>")

        repo_memory_path = REPO_MEMORY_DIR / f"{self.repo_name}.md" if self.repo_name else ""
        parts.append(_MEMORY_GUIDELINES.format(
            repo_memory_path=repo_memory_path,
            date=date.today().isoformat(),
            summary="- {bullet 1}\n- {bullet 2}\n- {bullet 3}",
        ))

        return append_to_system(system, "\n\n".join(parts))


# Recognised keys for a stored name preference (see "Preference extraction
# contract" above). Add new synonyms here — this is the single source of
# truth for what counts as a name-preference line.
_NAME_PREFERENCE_PATTERNS = [
    r"preferred_name[：:]\s*(.+)",
    r"名字偏好[：:]\s*(.+)",
    r"name preference[：:]\s*(.+)",
]


def _extract_name_preference(memory: str) -> str | None:
    """Scan memory content for a stored name preference and return it, or None.

    Returns the first matching line's captured value, in file order.
    """
    import re
    for line in memory.splitlines():
        line = line.strip().lstrip("-• ")
        for pattern in _NAME_PREFERENCE_PATTERNS:
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                return m.group(1).strip()
    return None


def _read_file(path: Path) -> str:
    """Read a file and return its content, or empty string if missing."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def ensure_memory_files(repo_name: str) -> None:
    """Create memory directory structure and stub files if they don't exist."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    REPO_MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    if not GLOBAL_MEMORY_FILE.exists():
        GLOBAL_MEMORY_FILE.write_text(
            "# Agent Memory\n\n## User Preferences\n\n## Notes\n", encoding="utf-8"
        )

    repo_file = REPO_MEMORY_DIR / f"{repo_name}.md"
    if not repo_file.exists():
        repo_file.write_text(
            f"# {repo_name}\n\n## Previous Analyses\n", encoding="utf-8"
        )
