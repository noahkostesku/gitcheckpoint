"""Conversation agent — handles general chat, planning, brainstorming."""

from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from src.tools.memory_tools import ALL_MEMORY_TOOLS

CONVERSATION_PROMPT = (
    "You are a conversational AI assistant that is part of GitCheckpoint — "
    "a system where every conversation is version-controlled like a Git repository. "
    "Engage naturally with the user. If they mention anything related to saving, "
    "branching, rewinding, or sharing the conversation, let the supervisor know "
    "so it can route to the right agent.\n\n"
    "You have access to long-term memory tools. Use save_memory when the user "
    "shares preferences or important context worth remembering. Use recall_memories "
    "to check for previously saved information when relevant."
)


def create_conversation_agent(model: ChatAnthropic):
    """Create a ReAct agent for general conversation with memory tools."""
    return create_react_agent(
        model=model,
        tools=ALL_MEMORY_TOOLS,
        name="conversation_agent",
        prompt=CONVERSATION_PROMPT,
    )
