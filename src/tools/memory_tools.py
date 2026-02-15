"""Long-term memory tools for cross-session persistence.

Uses LangGraph's InMemoryStore to save and recall user preferences,
notes, and context that persists across conversation threads.
"""

from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.tools import tool
from langgraph.store.memory import InMemoryStore

# Module-level store instance — shared across all agents
_store: InMemoryStore | None = None


def set_store(store: InMemoryStore) -> None:
    global _store
    _store = store


def get_store() -> InMemoryStore:
    if _store is None:
        raise RuntimeError("Memory store not initialized. Call set_store() first.")
    return _store


@tool
def save_memory(content: str, category: str = "general") -> str:
    """Save a piece of information to long-term memory for future reference.

    Use this when the user says something worth remembering across conversations,
    like preferences, important context, or recurring topics.

    Args:
        content: The information to remember
        category: Category for organization (e.g., 'preference', 'context', 'note')
    """
    store = get_store()
    key = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    store.put(
        namespace=("memories", category),
        key=key,
        value={"content": content, "saved_at": key},
    )
    return f"Saved to long-term memory [{category}]: {content}"


@tool
def recall_memories(category: str = "general", limit: int = 10) -> str:
    """Recall information from long-term memory.

    Use this to retrieve previously saved memories, preferences, or context.

    Args:
        category: Category to search in (e.g., 'preference', 'context', 'note', 'general')
        limit: Maximum number of memories to return
    """
    store = get_store()
    items = store.search(
        ("memories", category),
        limit=limit,
    )
    if not items:
        return f"No memories found in category '{category}'."

    lines = [f"Memories [{category}]:"]
    for item in items:
        content = item.value.get("content", "")
        saved_at = item.value.get("saved_at", "unknown")
        lines.append(f"  - [{saved_at}] {content}")
    return "\n".join(lines)


ALL_MEMORY_TOOLS = [save_memory, recall_memories]
