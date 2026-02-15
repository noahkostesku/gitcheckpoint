"""Supervisor graph — wires conversation, git, and GitHub agents together."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage, SystemMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from pydantic import BaseModel

# Max tokens to keep in conversation history when trimming.
# Claude Sonnet has 200k context; we keep ~100k for headroom.
MAX_HISTORY_TOKENS = 100_000

# When message count exceeds this, summarize older messages.
SUMMARIZE_AFTER = 20

# Number of recent messages to keep after summarization.
KEEP_RECENT = 6

from langgraph.checkpoint.memory import MemorySaver

from langgraph.store.memory import InMemoryStore

from src.agents.conversation_agent import create_conversation_agent
from src.agents.git_ops_agent import create_git_ops_agent
from src.agents.github_ops_agent import create_github_ops_agent
from src.checkpointer.git_checkpointer import GitCheckpointer
from src.config import Settings
from src.tools.git_tools import ALL_GIT_TOOLS, set_checkpointer
from src.tools.github_tools import ALL_GITHUB_TOOLS, init_github
from src.tools.memory_tools import set_store

SUPERVISOR_PROMPT = (
    "You are the GitCheckpoint supervisor. Route user requests:\n"
    "\n"
    "→ conversation_agent: General chat, planning, brainstorming, questions\n"
    "→ git_ops_agent: When user mentions: save, checkpoint, rewind, branch, "
    "fork, merge, diff, history, time travel, \"what if\", undo\n"
    "→ github_ops_agent: When user mentions: push, GitHub, share, issue, "
    "PR, pull request, gist, team, collaborate\n"
    "\n"
    "If uncertain, default to conversation_agent.\n"
    "IMPORTANT: After an agent has responded (you see AI messages after the "
    "user's message), you MUST choose FINISH. Only route to an agent when "
    "the latest message is from the user and no agent has responded yet."
)

AGENT_DESCRIPTIONS = {
    "conversation_agent": "our conversation specialist",
    "git_ops_agent": "our git operations specialist",
    "github_ops_agent": "our GitHub integration specialist",
}


class SupervisorState(TypedDict):
    """State shared across the supervisor graph."""

    messages: Annotated[list[BaseMessage], add_messages]
    next: str
    agent_responded: bool
    summary: str


def create_supervisor(
    agents: list,
    model: ChatAnthropic,
    prompt: str,
) -> StateGraph:
    """Build a supervisor StateGraph that routes between agents.

    Args:
        agents: Compiled agent graphs (from create_react_agent).
        model: The LLM used for routing decisions.
        prompt: System prompt that guides routing logic.

    Returns:
        An uncompiled ``StateGraph`` — call ``.compile()`` on it.
    """
    agent_names = [a.name for a in agents]
    options = agent_names + ["FINISH"]

    class Router(BaseModel):
        """The supervisor's routing decision."""

        next: str

    router_model = model.with_structured_output(Router)

    def supervisor_node(state: SupervisorState) -> dict:
        # If an agent already responded this turn, finish immediately.
        # Check by seeing if the last message is from a human (new turn)
        # or from an agent (already responded).
        msgs = state.get("messages", [])
        if state.get("agent_responded", False):
            # Check if a new user message arrived (new turn)
            if msgs and msgs[-1].type == "human":
                pass  # New user message — route again
            else:
                return {"next": "FINISH"}

        # Trim old messages to stay within context limits
        trimmed = trim_messages(
            msgs,
            max_tokens=MAX_HISTORY_TOKENS,
            token_counter="approximate",
            strategy="last",
            start_on="human",
            include_system=True,
        )

        # Prepend existing summary as context if available
        summary = state.get("summary", "")
        system_content = prompt + "\n\nChoose the next agent to handle this request. " + f"Options: {', '.join(options)}. " + "Use FINISH when the conversation turn is complete."
        if summary:
            system_content += f"\n\nPrevious conversation summary:\n{summary}"

        system = SystemMessage(content=system_content)
        result = router_model.invoke([system] + trimmed)
        chosen = result.next

        # Announce routing to the user
        if chosen != "FINISH" and chosen in AGENT_DESCRIPTIONS:
            desc = AGENT_DESCRIPTIONS[chosen]
            routing_msg = AIMessage(
                content=f"Routing you to {desc}..."
            )
            return {"next": chosen, "messages": [routing_msg], "agent_responded": False}

        return {"next": chosen}

    def maybe_summarize(state: SupervisorState) -> dict:
        """Summarize old messages when conversation gets long.

        Replaces older messages with a summary, keeping the most recent
        KEEP_RECENT messages intact.
        """
        msgs = state.get("messages", [])
        if len(msgs) <= SUMMARIZE_AFTER:
            return {}

        # Messages to summarize (all but the most recent KEEP_RECENT)
        old_msgs = msgs[:-KEEP_RECENT]
        existing_summary = state.get("summary", "")

        summary_prompt = "Create a concise summary of the conversation so far. "
        if existing_summary:
            summary_prompt += f"There is an existing summary to extend:\n{existing_summary}\n\n"
        summary_prompt += "New messages to incorporate into the summary:"

        summary_input = [SystemMessage(content=summary_prompt)] + old_msgs
        response = model.invoke(summary_input)
        new_summary = response.content if isinstance(response.content, str) else str(response.content)

        # Delete old messages from state using RemoveMessage
        delete_msgs = [RemoveMessage(id=m.id) for m in old_msgs if hasattr(m, "id") and m.id]

        return {"summary": new_summary, "messages": delete_msgs}

    def _make_agent_node(agent):
        """Wrap a compiled subgraph agent to prevent message explosion.

        The subgraph returns ALL messages (input + output). We only want
        the NEW messages it generated, so we slice off the input echoes.
        """

        def agent_node(state: SupervisorState, config: RunnableConfig) -> dict:
            input_msgs = state["messages"]

            # Trim messages before passing to agent to prevent context overflow
            trimmed = trim_messages(
                input_msgs,
                max_tokens=MAX_HISTORY_TOKENS,
                token_counter="approximate",
                strategy="last",
                start_on="human",
                include_system=True,
            )
            n_trimmed = len(trimmed)

            # Inject thread context and summary so agents have full context
            thread_id = config.get("configurable", {}).get("thread_id", "default")
            summary = state.get("summary", "")
            context_parts = [f"The current conversation thread_id is: {thread_id}"]
            if summary:
                context_parts.append(f"Previous conversation summary:\n{summary}")
            context_msg = SystemMessage(content="\n\n".join(context_parts))
            agent_input = [context_msg] + trimmed

            result = agent.invoke({"messages": agent_input})
            all_msgs = result.get("messages", [])

            # Only return messages after the trimmed input + context msg
            new_messages = all_msgs[n_trimmed + 1:]

            return {"messages": new_messages, "agent_responded": True}

        agent_node.__name__ = agent.name
        return agent_node

    builder = StateGraph(SupervisorState)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("maybe_summarize", maybe_summarize)

    for agent in agents:
        builder.add_node(agent.name, _make_agent_node(agent))

    builder.add_edge(START, "supervisor")

    # Conditional routing from supervisor to agents or END
    # When FINISH, go to maybe_summarize first
    routing_map = {name: name for name in agent_names}
    routing_map["FINISH"] = "maybe_summarize"

    builder.add_conditional_edges(
        "supervisor",
        lambda state: state["next"],
        routing_map,
    )

    # Summarization leads to END
    builder.add_edge("maybe_summarize", END)

    # All agents route back to supervisor after completing
    for name in agent_names:
        builder.add_edge(name, "supervisor")

    return builder


def build_supervisor_graph(settings: Settings, checkpointer: GitCheckpointer | None = None):
    """Build and compile the supervisor multi-agent graph.

    Args:
        settings: Application settings (provides API key, checkpoint dir).
        checkpointer: Optional pre-built checkpointer. If None, one is created
            from ``settings.checkpoint_dir``.

    Returns:
        A compiled LangGraph ``Pregel`` application.
    """
    model = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=settings.anthropic_api_key,
    )

    # Create agents
    convo_agent = create_conversation_agent(model)
    git_agent = create_git_ops_agent(model, git_tools=ALL_GIT_TOOLS)
    github_agent = create_github_ops_agent(model, github_tools=ALL_GITHUB_TOOLS)

    # Build supervisor state graph
    workflow = create_supervisor(
        agents=[convo_agent, git_agent, github_agent],
        model=model,
        prompt=SUPERVISOR_PROMPT,
    )

    # Create GitCheckpointer for user-facing git operations (tools)
    if checkpointer is None:
        checkpointer = GitCheckpointer(settings.checkpoint_dir)

    # Wire the checkpointer into git tools so they can access the repo
    set_checkpointer(checkpointer)

    # Wire GitHub client and checkpointer into GitHub tools
    init_github(settings, checkpointer=checkpointer)

    # Initialize long-term memory store for cross-session persistence
    store = InMemoryStore()
    set_store(store)

    # Create state checkpointer based on settings.
    # The GitCheckpointer is used only by git tools for user-facing
    # checkpoint operations, avoiding concurrent git access conflicts.
    state_checkpointer = _create_state_checkpointer(settings)

    app = workflow.compile(checkpointer=state_checkpointer, store=store)
    app.step_timeout = 120
    return app


def _create_state_checkpointer(settings: Settings):
    """Create the LangGraph state checkpointer based on settings.

    Supports:
      - "memory" (default): In-memory, fast, lost on restart
      - "postgres": PostgreSQL-backed, persistent across restarts
        Requires: pip install langgraph-checkpoint-postgres
        Set STATE_BACKEND_URI=postgresql://user:pass@host:5432/db
      - "redis": Redis-backed, high-performance persistent
        Requires: pip install langgraph-checkpoint-redis
        Set STATE_BACKEND_URI=redis://host:6379
    """
    import logging
    logger = logging.getLogger("gitcheckpoint")
    backend = settings.state_backend.lower()

    if backend == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            if not settings.state_backend_uri:
                logger.warning("STATE_BACKEND=postgres but no URI set — falling back to memory")
                return MemorySaver()
            saver = PostgresSaver.from_conn_string(settings.state_backend_uri)
            saver.setup()
            logger.info("Using PostgreSQL state backend")
            return saver
        except ImportError:
            logger.warning("langgraph-checkpoint-postgres not installed — falling back to memory")
            return MemorySaver()
        except Exception as e:
            logger.warning("Postgres connection failed (%s) — falling back to memory", e)
            return MemorySaver()

    elif backend == "redis":
        try:
            from langgraph.checkpoint.redis import RedisSaver
            if not settings.state_backend_uri:
                logger.warning("STATE_BACKEND=redis but no URI set — falling back to memory")
                return MemorySaver()
            saver = RedisSaver.from_conn_string(settings.state_backend_uri)
            logger.info("Using Redis state backend")
            return saver
        except ImportError:
            logger.warning("langgraph-checkpoint-redis not installed — falling back to memory")
            return MemorySaver()
        except Exception as e:
            logger.warning("Redis connection failed (%s) — falling back to memory", e)
            return MemorySaver()

    else:
        # Default: in-memory (development)
        return MemorySaver()
