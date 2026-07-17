"""Compact middleware: auto-summarises conversation when context gets too long.

Configuration contract
-----------------------
`COMPACT_THRESHOLD` and `KEEP_MESSAGES` are read from the environment at
import time (`HARNESS_COMPACT_THRESHOLD`, `HARNESS_KEEP_MESSAGES`), falling
back to the documented defaults below if unset or invalid. This makes the
thresholds a declared, overridable contract rather than a silent constant.

Invariant: after `maybe_compact()` returns, `count_tokens_approximately()`
of the returned list is either (a) the original list unchanged (below
threshold, or nothing left to summarise), or (b) one summary message plus
the last `KEEP_MESSAGES` messages verbatim. It is never partially compacted.

Failure mode: if the summarisation LLM call itself fails (provider error,
timeout), compaction falls back to hard truncation — keep only the last
`KEEP_MESSAGES` messages and drop the rest silently — rather than raising
and losing the whole turn. This trades summary quality for availability:
an agent that can't summarise should still be able to keep talking.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.messages.utils import count_tokens_approximately

from .base import AgentMiddleware


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Tokens before triggering compaction. Default leaves headroom under typical
# 128k-200k model context windows while avoiding constant re-summarisation.
COMPACT_THRESHOLD = _env_int("HARNESS_COMPACT_THRESHOLD", 50_000)

# Recent messages kept verbatim after compaction. Default is large enough to
# usually span a full tool-call/tool-response pair plus a couple of
# conversational turns, so the agent doesn't lose immediate context.
KEEP_MESSAGES = _env_int("HARNESS_KEEP_MESSAGES", 10)

_SUMMARY_PROMPT = """Summarise the following conversation history concisely.
Focus on:
1. Key decisions and findings so far
2. Files already explored and what was learned
3. Current state of the analysis
4. Any pending items

Keep it brief but complete enough to continue the task.

---
{history}
"""


class CompactMiddleware(AgentMiddleware):
    """Compresses old messages into a summary when the token count exceeds the threshold."""

    def __init__(self, llm: Any):
        self.llm = llm

    def maybe_compact(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        """Return a (possibly compacted) message list. Runs synchronously."""
        total = count_tokens_approximately(messages)
        if total < COMPACT_THRESHOLD:
            return messages

        keep = messages[-KEEP_MESSAGES:]
        to_summarize = messages[:-KEEP_MESSAGES]

        if not to_summarize:
            return messages

        history_text = "\n".join(
            f"{m.__class__.__name__}: {_message_text(m)[:300]}"
            for m in to_summarize
        )
        prompt = _SUMMARY_PROMPT.format(history=history_text)

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
        except Exception as e:
            # Failure mode: summarisation itself failed — fall back to hard
            # truncation rather than losing the turn entirely.
            print(f"\n[Compact] Summarisation failed ({e}); falling back to truncation.\n")
            return keep

        summary = HumanMessage(
            content=(
                f"[Context summary — {len(to_summarize)} earlier messages compacted]\n"
                f"{response.content}"
            )
        )

        print(
            f"\n[Compact] Compressed {len(to_summarize)} messages "
            f"({total:,} tokens → ~{count_tokens_approximately(keep):,} tokens kept)\n"
        )
        return [summary] + list(keep)


def _message_text(msg: AnyMessage) -> str:
    """Extract plain text from a message for summarisation."""
    if isinstance(msg.content, str):
        return msg.content
    if isinstance(msg.content, list):
        # Handle multi-part content blocks
        return " ".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in msg.content
        )
    return str(msg.content)
