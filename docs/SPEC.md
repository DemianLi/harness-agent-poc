# Harness Agent — Six-Layer Architecture Specification

This document is the normative specification for the six layers that make up
this harness: **Model**, **Tools**, **Memory**, **Context (Compact)**,
**Permission (HITL)**, and **Orchestration (control loop)** — plus two
additions layered on top: the **Interaction** tool (§2b, `ask_user`) and the
**Feedback** layer (§7), which is explicitly called out as an extension
beyond the base six rather than a seventh structural requirement of the
pattern. Each section defines the interface/data contract, configuration
parameters and their rationale, the error taxonomy, invariants, and failure
modes for that layer. Where a layer has an explicit trust boundary (a
limitation it deliberately does not solve), that boundary is stated so it is
a documented decision, not a silent gap.

Status: this spec describes the implementation as of this revision. If code
and spec disagree, that is a bug in one of the two — file it as such.

---

## 1. Model Layer

**Module:** `harness_agent/llm/providers.py`

### Interface contract

```
create_llm(provider: Provider | None = None) -> BaseChatModel
```

- MUST return an object supporting `.bind_tools(tools)`, `.invoke(messages)`,
  and `.stream(messages)`, constructed with `streaming=True`.
- Provider resolution order: explicit `provider` argument →
  `[llm].provider` in `~/.harness-agent/config.toml` → environment
  auto-detect (`AZURE_OPENAI_API_KEY` present ⇒ `"azure"`) → `"claude"`.
- Model resolution order: `[llm].model` in config.toml →
  `DEFAULT_MODELS[provider]` (Azure has no static default; it always reads
  `AZURE_OPENAI_DEPLOYMENT`).

### Error taxonomy

| Exception | Raised when | Fatal? |
|---|---|---|
| `ProviderUnknownError` | `provider` is not one of `claude/openai/azure/gemini` | Yes — fails before any network call |
| `ProviderConfigError` | A required env var (endpoint/key/deployment) is missing | Yes — fails before any network call, with an actionable message naming the missing var |

Both are raised eagerly inside `create_llm()`, never surfaced as a bare
`KeyError`/`ValueError`.

### Retry contract — `invoke_with_retry(model, messages, max_retries=MAX_RETRIES)`

- Retries only errors classified transient by `_is_retryable`: an HTTP
  status in `{408, 429, 500, 502, 503, 504}` (read from `status_code` on the
  exception or its `.response`), or an exception class named
  `APIConnectionError` / `APITimeoutError` / `Timeout` / `ConnectionError`
  (covers provider SDKs without importing every SDK's exception hierarchy).
- Backoff: exponential, `RETRY_BACKOFF_BASE_S * 2**attempt`, starting at
  `RETRY_BACKOFF_BASE_S = 1.0`s, up to `MAX_RETRIES = 2` retries (3 attempts
  total). These are conservative defaults for an interactive session where a
  human is waiting — not tuned for a batch pipeline.
- Non-transient errors (bad request, content filter, auth failure) are
  re-raised on the first attempt — no retry budget is spent on an error that
  cannot succeed on retry.

### Failure mode (caller contract, enforced in `agent.py::agent_node`)

- `BadRequestError` (content filter / malformed request) → degrade to a
  visible `AIMessage` warning; the session MUST stay alive.
- Any other exception surviving `invoke_with_retry`'s budget → degrade to a
  visible `AIMessage` warning; the session MUST stay alive.
- The control loop (§6) never crashes because of a Model-layer failure.

### Explicit trust boundary

No cost/token metering, no per-request timeout override, no cross-provider
error-message normalization beyond the retry classifier above. Acceptable
for a single-user CLI; a multi-tenant service needs a metering/budget layer
in front of this one.

---

## 2. Tools Layer

**Module:** `harness_agent/tools/filesystem.py`

### Interface contract

Six tools, each a `@tool`-decorated function with a Pydantic `args_schema`
(`LsInput`, `ReadFileInput`, `GlobInput`, `GrepInput`, `WriteFileInput`,
`EditFileInput`) — the schema IS the input contract and is enforced by
LangChain before the function body runs.

Every tool returns a plain string:
- **Success:** short human-readable confirmation, or the requested content.
- **Failure:** a string starting with `"Error: {code}: "` where `code` is
  one of the constants in `ErrorCode` (`path_not_found`, `not_a_directory`,
  `is_directory`, `file_not_found`, `invalid_regex`, `not_unique`,
  `io_error`). Callers — including the LLM reading the tool result — can
  rely on this prefix being stable; the trailing message text is not part of
  the contract and may change.

### Configuration bounds (named constants, not magic numbers)

| Constant | Value | Rationale |
|---|---|---|
| `DEFAULT_READ_LIMIT` | 150 lines | Fits inside a single LLM turn's context budget alongside other tool output for the common case (small/medium source files) without forcing pagination |
| `GREP_MAX_FILES` | 100 files | Bounds a single grep call's cost regardless of repo size |
| `GREP_MAX_RESULTS` | 200 lines | Bounds a single grep call's output regardless of match count |

### Risk classification (drives §5 Permission layer)

- `write_file` → `HIGH_RISK_TOOLS`. It performs a full, unconditional
  overwrite; a single bad call can silently destroy an existing file.
- `edit_file` → NOT high-risk, because it enforces two structural
  safeguards that make it self-limiting: (1) the target file must already
  exist, and (2) it fails closed (`not_unique` error) if `old_string` isn't
  found exactly once. It cannot silently clobber unintended content the way
  a full overwrite can.
- `ls` / `read_file` / `glob` / `grep` are read-only → never require
  approval.

This classification is the single source of truth; `middleware/hitl.py`
does not re-derive risk, it only renders the prompt for whatever
`HIGH_RISK_TOOLS` says is risky.

### Explicit trust boundary

**No sandbox.** Tools accept absolute paths and operate with the OS-level
permissions of the running process — no path allowlist, no per-user
isolation. This is an accepted trade-off for a single-user local CLI where
the human operating the tool and the human running the agent are the same
person. **Do not** expose these tools to multiple users or untrusted input
without adding a path-allowlist/sandboxing middleware first — that is
explicitly out of scope for this layer as specified.

---

## 2b. Interaction Tool (`ask_user`)

**Module:** `harness_agent/tools/interaction.py`

### Interface contract

```
ask_user(question: str, options: list[str] = []) -> str
```

Blocks synchronously on console input and returns the human's answer as a
plain string (if `options` is given and the human types a number in range,
the corresponding option string is returned instead of the raw digit).

### Risk classification

Read-only, side-effect-free → never a member of `HIGH_RISK_TOOLS`, never
requires HITL approval (§5). It is bound to the model alongside the
filesystem tools (`agent.py::ALL_TOOLS = FILESYSTEM_TOOLS + INTERACTION_TOOLS`).

### Explicit trust boundary — this does not force clarification

Nothing in the graph *requires* the model to call `ask_user` before acting
on an ambiguous request; `prompts/system.md` instructs it to, but that is a
convention the model can still choose not to follow. What this tool changes
is **observability**: every clarification attempt now appears in the same
tool-call trace as `read_file`/`write_file` calls, instead of living only as
free-form text the model may or may not have actually asked. A hard
guarantee ("must always ask before X") would require the control loop
itself to detect ambiguity and force a branch to this tool — that is not
implemented; see §6 for the orchestration layer's actual (single-path,
no-planner) shape.

`_stream_response` in `main.py` excludes `ask_user` calls when counting
"did this turn do something" for the §7 feedback prompt — asking a
question is not, by itself, a completed task.

---

## 3. Memory Layer

**Module:** `harness_agent/middleware/memory.py`

### Schema contract

`memory/AGENTS.md` (global) MUST contain, in order:
```
# Agent Memory
## User Preferences
## Notes
```
`memory/repos/{repo_name}.md` (per-repo) MUST contain, in order:
```
# {repo_name}
## Previous Analyses
```
Both `## Previous Analyses` and the file's overall shape are load-bearing:
the agent's memory-update instructions (`_MEMORY_GUIDELINES` in the same
module) target `"## Previous Analyses\n"` as the exact-match anchor for
`edit_file` appends (§2's `edit_file` contract: fails closed, doesn't
corrupt, if the anchor is missing or duplicated).

### Preference extraction contract

`_extract_name_preference` recognizes the keys enumerated in the module-level
`_NAME_PREFERENCE_PATTERNS` list (case-insensitive): `preferred_name:`,
`名字偏好:`, `name preference:`. Lines are scanned in file order; the
**first** matching line wins. Later occurrences of the same key are ignored,
not merged — this is a deliberate simplification for small, human-curated
memory files: updates are expected to replace the existing line, not append
a second, conflicting one.

### Failure mode

- Missing file → `_read_file` returns `""`; the agent proceeds with no
  memory context (not an error).
- Malformed file (headers renamed/removed) → degrades to "no preference
  detected"; `edit_file` appends will fail closed per the Tools contract
  rather than corrupting the file.

### Explicit trust boundary

Single global memory file, no per-user namespace, no schema validation on
write, no vector/semantic recall — appropriate for one local user with a
handful of repos; not a multi-tenant memory store.

---

## 4. Context Layer (Compact)

**Module:** `harness_agent/middleware/compact.py`

### Configuration contract

| Env var | Default | Rationale |
|---|---|---|
| `HARNESS_COMPACT_THRESHOLD` | 50,000 tokens | Leaves headroom under typical 128k–200k model context windows while avoiding constant re-summarization |
| `HARNESS_KEEP_MESSAGES` | 10 messages | Large enough to usually span a full tool-call/tool-response pair plus a couple of conversational turns, so recent working context survives verbatim |

Both fall back to the documented default if the env var is unset or fails
`int()` parsing — this is a declared, overridable contract, not a silent
constant.

### Invariant

After `maybe_compact()` returns, the result is always one of:
1. The original message list, unchanged (below threshold, or nothing left
   to summarize after reserving `KEEP_MESSAGES`).
2. Exactly one summary `HumanMessage` followed by the last `KEEP_MESSAGES`
   messages, verbatim.

There is no partially-compacted state.

### Failure mode

If the summarization LLM call itself raises (provider error, timeout, or a
Model-layer error that exhausted `invoke_with_retry`'s budget), compaction
falls back to **hard truncation** — keep only the last `KEEP_MESSAGES`
messages and drop the rest — rather than propagating the exception and
losing the turn. This trades summary quality for availability: an agent
that cannot summarize should still be able to keep talking.

---

## 5. Permission Layer (HITL)

**Module:** `harness_agent/middleware/hitl.py` (approval + audit),
`harness_agent/agent.py::tool_node_with_hitl` (enforcement point)

### Approval contract

- Risk classification is owned entirely by §2 (`HIGH_RISK_TOOLS`); this
  layer does not re-derive it.
- **Batch, atomic approval:** all risky tool calls from a single agent turn
  are shown together in one `request_approval()` call; the human's yes/no
  decision applies to the entire batch — there is no partial approval of
  a subset.
- **Configurable durability — `approval_scope`:** resolved by
  `resolve_approval_scope(override) -> "session" | "call"` (explicit
  override — e.g. the `--approval-scope` CLI flag — > `HARNESS_APPROVAL_SCOPE`
  env var > `"session"` default). An unrecognised env value silently falls
  back to `"session"` (a runtime setting, not a startup precondition); an
  unrecognised `--approval-scope` CLI value is rejected up front by
  `click.Choice` (fail fast on operator typos).
  - `"session"` (default, backward-compatible): approval state lives in
    `AgentState.writes_approved`, which is **monotonic** per `thread_id` —
    once set `True`, it is never reset back to `False` within that thread.
    A rejection leaves it `False` and the next high-risk call re-prompts.
    There is no "approve once for this specific file" scope — approval is
    session-wide once granted.
  - `"call"`: `tool_node_with_hitl` treats `writes_approved` as always
    `False` regardless of what is stored in state — every batch of
    high-risk calls is re-prompted, with no session-wide memory of prior
    approvals. Use this when "must confirm every high-risk operation" is a
    hard requirement rather than a one-time session grant.

### Audit contract — `log_decision(repo_name, tool_calls, approved)`

- Appends one JSON object per line (JSONL) to `memory/audit.log`:
  `{"timestamp": <ISO8601 UTC>, "repo": ..., "approved": bool, "tool_calls": [{"name", "args"}, ...]}`.
- **Append-only.** Nothing in this codebase mutates or truncates the file.
- Called for every batch decision — approved or rejected — before the tool
  calls (if approved) execute.
- **Non-fatal on write failure:** an unwritable `memory/` directory prints a
  warning and does not block the agent turn. Audit logging is
  best-effort observability, not a hard gate — the gate is the human
  approval prompt itself.

### Explicit trust boundary

Approval UI is a blocking terminal prompt (`rich`/`console.input`) — single
synchronous human, no async review queue, no RBAC, no per-tool-call granular
policy (allow/deny/ask by path pattern, for example). A product surface
needs a richer policy engine in front of this contract, not a replacement
of it.

---

## 6. Orchestration Layer (control loop)

**Module:** `harness_agent/agent.py`

### State machine

```
entry ─▶ "agent" ──tool_calls present──▶ "tools" ─▶ "agent"  (repeat)
                 \──no tool_calls───────▶ END
```

Implemented as a `langgraph.StateGraph(AgentState)` with LangGraph's
`tools_condition` as the conditional edge. One LLM call per "agent" node
visit, followed by at most one batch of tool calls per "tools" node visit.
There is no planner node and no sub-agent fan-out — this is a single linear
ReAct-style loop, not a multi-agent orchestrator.

### `AgentState` contract and invariants

| Field | Invariant |
|---|---|
| `messages` | Accumulates via `add_messages` reducer; never rewritten wholesale except by Context-layer compaction (§4), which replaces the list under its own documented invariant |
| `memory_loaded` | Set `True` at most once per `thread_id`; never reset |
| `global_memory`, `repo_memory` | Set once, alongside `memory_loaded`; read-only afterward within the thread |
| `writes_approved` | Monotonically set within the field itself once `True` (see §5); whether that stored value is *honoured* on the next high-risk call additionally depends on `approval_scope` — `"session"` honours it, `"call"` ignores it |

### Persistence contract

State is checkpointed by `langgraph.checkpoint.memory.MemorySaver` —
**in-process memory only.** It does NOT survive a process restart and is
NOT shared across concurrent processes. Its sole purpose is letting
`main.py::_repl` resume the same `thread_id` across turns within one CLI
invocation. Do not treat it as durable storage; a product surface needs a
real checkpoint backend (database-backed `BaseCheckpointSaver`) here.

### Failure mode

Per §1, any Model-layer error is caught inside `agent_node` and converted to
a visible `AIMessage` — the graph never raises out of a node during normal
operation, so the control loop itself has no undocumented crash path.

---

## 7. Feedback Layer (extension beyond the base six)

**Module:** `harness_agent/middleware/feedback.py`,
`harness_agent/main.py::_repl`/`_stream_response` (trigger point)

This layer is explicitly **not** one of the original six (Model, Tools,
Memory, Context, Permission, Orchestration) — it is called out separately
so it isn't mistaken for a structural requirement of the harness pattern
itself. It exists to close the gap identified in the prior review: no
mechanism previously collected user-perceived quality signal after a turn.

### Trigger contract — `maybe_prompt_feedback(repo_name, tool_names_this_turn)`

- Fires only when `tool_names_this_turn` is non-empty — i.e., the turn
  executed at least one real tool call. A purely conversational reply (the
  model answered from context with zero tool calls) does not trigger it.
  `ask_user` calls are excluded from this list by `_stream_response` (§2b) —
  asking a clarifying question is not, on its own, a completed task.
- Always skippable: pressing Enter with no input returns immediately and
  writes nothing. Any input not recognised as good/bad (`g`/`good`/`b`/`bad`,
  case-insensitive) is treated as a skip, never an error — a malformed
  answer must never block the next turn from proceeding.
- On a `"bad"` rating, one optional free-text follow-up ("What went
  wrong") is collected; `"good"` collects no further input.

### Storage contract

Append-only JSONL at `memory/feedback.log`:
`{"timestamp": <ISO8601 UTC>, "repo": ..., "tool_calls_this_turn": [...], "rating": "good"|"bad", "comment": str}`.
One record per non-skipped rating; skipped prompts write nothing. Write
failure is non-fatal (same contract as §5's audit log) — a warning is
printed and the turn proceeds.

### Explicit trust boundary

This is local, unaggregated, single-user telemetry — there is no rollup,
no dashboard, no correlation with a specific model/provider/session for
analysis. A product surface needs a real analytics pipeline consuming this
log (or replacing it with a hosted telemetry backend); this layer only
guarantees the signal is captured at the point of interaction.

---

## Cross-layer summary

| Layer | Formal contract now covers | Still explicitly out of scope (by design) |
|---|---|---|
| Model | Provider resolution, error taxonomy, retry policy, degrade-not-crash | Cost metering, cross-provider error message normalization |
| Tools | Input schemas, error-code taxonomy, bounded output, risk classification | Path sandboxing / multi-tenant isolation |
| Interaction (`ask_user`) | Blocking clarification tool, observable in the tool-call trace | Cannot be forced by the control loop — model-discretionary |
| Memory | File schema, preference-extraction rule, failure mode | Multi-user namespace, semantic recall |
| Context | Configurable thresholds w/ rationale, compaction invariant, failure mode | Adaptive/semantic compaction |
| Permission | Batch-approval semantics, configurable `approval_scope`, audit log | Async review queue, RBAC, per-path policy |
| Orchestration | State machine, state invariants, persistence contract | Planning layer, multi-agent fan-out, durable checkpoint backend |
| Feedback (extension) | Skippable post-turn rating, append-only log | Aggregation/dashboard, per-model/session analytics |

Anything in the right-hand column is a deliberate scope boundary, not an
oversight — see the previous architecture review for what's required to
close those gaps for a multi-tenant product surface.
