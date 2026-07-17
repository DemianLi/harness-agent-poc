"""LangGraph agent with the full middleware stack."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from openai import BadRequestError
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from .llm.providers import invoke_with_retry
from .middleware.compact import CompactMiddleware
from .middleware.hitl import log_decision, request_approval, resolve_approval_scope
from .middleware.memory import MemoryMiddleware, ensure_memory_files
from .tools.filesystem import FILESYSTEM_TOOLS, HIGH_RISK_TOOLS
from .tools.interaction import INTERACTION_TOOLS

# All tools bound to the model: filesystem tools + the ask_user clarification
# tool. Risk classification (HIGH_RISK_TOOLS) is unaffected — ask_user is
# read-only and is never in that set (see tools/interaction.py).
ALL_TOOLS = FILESYSTEM_TOOLS + INTERACTION_TOOLS


# --------------------------------------------------------------------------- #
# State                                                                        #
# --------------------------------------------------------------------------- #
#
# Orchestration contract (control loop): a single linear ReAct-style loop —
#
#   entry -> "agent" --tool_calls present--> "tools" -> "agent" (repeat)
#                    \--no tool_calls------> END
#
# implemented via LangGraph's `tools_condition`. There is no planner node and
# no sub-agent fan-out; every turn is one LLM call followed by at most one
# batch of tool calls. State is checkpointed by `MemorySaver`, which is
# **in-process memory only** — it does not survive a process restart and is
# not shared across concurrent processes. Do not rely on it as durable
# storage; it exists solely to let `_repl` resume the same thread across
# turns within one CLI invocation.

class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    # Initialised once at startup. Invariant: once True, memory_loaded is
    # never reset for the lifetime of a thread_id.
    memory_loaded: bool
    global_memory: str
    repo_memory: str
    # True once the user has approved any write_file call this session;
    # subsequent write_file calls skip the HITL prompt automatically.
    # Invariant: monotonic per thread_id — set True -> False transitions
    # never happen. A rejected approval leaves this False and re-prompts
    # on the next high-risk tool call.
    writes_approved: bool


# --------------------------------------------------------------------------- #
# Graph builder                                                                #
# --------------------------------------------------------------------------- #

def build_graph(llm: Any, repo_name: str, approval_scope: str | None = None) -> Any:
    """Build and compile the LangGraph agent graph.

    Args:
        llm: A LangChain chat model.
        repo_name: Name of the repo being analysed (used for memory + reports path).
        approval_scope: "session" (default) or "call" — see
            `middleware/hitl.py::resolve_approval_scope` for the contract.
            None resolves from the `HARNESS_APPROVAL_SCOPE` env var.

    Returns:
        A compiled LangGraph app.
    """
    system_prompt = _load_system_prompt(repo_name)
    approval_scope = resolve_approval_scope(approval_scope)

    memory_mw = MemoryMiddleware(repo_name=repo_name)
    compact_mw = CompactMiddleware(llm=llm)
    model_with_tools = llm.bind_tools(ALL_TOOLS)

    ensure_memory_files(repo_name)

    # ------------------------------------------------------------------ #
    # Nodes                                                                #
    # ------------------------------------------------------------------ #

    def agent_node(state: AgentState) -> dict:
        updates: dict[str, Any] = {}

        # Load memory once at the start of the session
        if not state.get("memory_loaded"):
            init = memory_mw.before_agent(state)
            if init:
                updates.update(init)
                state = {**state, **init}

        messages = compact_mw.maybe_compact(state["messages"])
        system = memory_mw.inject_system(system_prompt, state)

        try:
            response = invoke_with_retry(
                model_with_tools, [SystemMessage(content=system)] + messages
            )
        except BadRequestError as e:
            # Azure/OpenAI content filter or other 400 errors — not retryable,
            # surface gracefully instead of crashing the whole process.
            error_detail = _extract_content_filter_reason(e)
            response = AIMessage(
                content=f"⚠️ Request blocked by the LLM provider: {error_detail}\n"
                        f"Try rephrasing your last message or starting a new session."
            )
        except Exception as e:
            # Any other provider error left over after invoke_with_retry's
            # retry budget is exhausted (or a non-transient error it didn't
            # retry). Contract: the session MUST stay alive — degrade to a
            # visible error message rather than propagating and killing the
            # REPL loop.
            response = AIMessage(
                content=f"⚠️ LLM call failed after retries: {e}\n"
                        f"Try again, or switch providers with --model."
            )

        updates["messages"] = [response]
        return updates

    def tool_node_with_hitl(state: AgentState) -> dict:
        """Execute tools; gate write_file behind approval per `approval_scope`."""
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return {"messages": []}

        # In "call" scope, a prior approval never counts — every batch of
        # high-risk calls is re-prompted. In "session" scope (default), a
        # prior approval this thread skips future prompts (see AgentState's
        # `writes_approved` invariant).
        writes_approved: bool = state.get("writes_approved", False) and approval_scope == "session"

        risky = [tc for tc in last.tool_calls if tc["name"] in HIGH_RISK_TOOLS
                 and not writes_approved]
        safe  = [tc for tc in last.tool_calls if tc["name"] not in HIGH_RISK_TOOLS
                 or writes_approved]

        tool_messages = []
        state_updates: dict[str, Any] = {}

        # Run safe / already-approved tools immediately
        if safe:
            safe_node = ToolNode(ALL_TOOLS)
            safe_ai = AIMessage(content="", tool_calls=safe)
            result = safe_node.invoke({"messages": state["messages"][:-1] + [safe_ai]})
            tool_messages.extend(result["messages"])

        # Handle risky tools — ask (subject to approval_scope), then record the decision
        if risky:
            approved = request_approval(risky)
            log_decision(repo_name=repo_name, tool_calls=risky, approved=approved)

            if approved:
                state_updates["writes_approved"] = True  # meaningful only in "session" scope
                risky_node = ToolNode(ALL_TOOLS)
                risky_ai = AIMessage(content="", tool_calls=risky)
                result = risky_node.invoke({"messages": state["messages"][:-1] + [risky_ai]})
                tool_messages.extend(result["messages"])
            else:
                for tc in risky:
                    tool_messages.append(ToolMessage(
                        content="Tool call rejected by user.",
                        tool_call_id=tc["id"],
                    ))

        return {"messages": tool_messages, **state_updates}

    # ------------------------------------------------------------------ #
    # Graph assembly                                                       #
    # ------------------------------------------------------------------ #

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node_with_hitl)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=MemorySaver())


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _load_system_prompt(repo_name: str) -> str:
    prompt_file = Path(__file__).parent / "prompts" / "system.md"
    text = prompt_file.read_text(encoding="utf-8")
    return text.replace("{repo_name}", repo_name)


def _extract_content_filter_reason(e: BadRequestError) -> str:
    """Pull a human-readable reason out of an Azure content filter error."""
    try:
        body = e.response.json()
        inner = body["error"].get("innererror", {})
        result = inner.get("content_filter_result", {})
        triggered = [
            f"{category}({info['severity']})"
            for category, info in result.items()
            if info.get("filtered")
        ]
        return f"content filter triggered — {', '.join(triggered)}" if triggered else str(e)
    except Exception:
        return str(e)
