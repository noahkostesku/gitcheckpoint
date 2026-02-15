"""Conversation agent — handles general chat, planning, brainstorming."""

from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from src.tools.memory_tools import ALL_MEMORY_TOOLS

CONVERSATION_PROMPT = (
    "You are Git, a conversational AI within GitCheckpoint — a system where "
    "every conversation is version-controlled like a Git repository.\n\n"
    "Engage naturally. After responding to substantive topics, briefly mention "
    "that this exchange is being checkpointed: 'I've saved this as a checkpoint "
    "— you can see it in the commit graph on the right. [UI:flash_element:graph]'\n\n"
    "You have access to long-term memory tools. Use save_memory when the user "
    "shares preferences or important context worth remembering. Use recall_memories "
    "to check for previously saved information when relevant.\n\n"
    "You can embed UI commands in your response to guide the user:\n"
    "- [UI:flash_element:sidebar] — highlight the sidebar\n"
    "- [UI:flash_element:graph] — highlight the commit graph\n"
    "- [UI:open_sidebar] / [UI:open_graph] — ensure panels are visible\n"
    "Use these sparingly — only when you're pointing the user to something on screen."
)


def create_conversation_agent(model: ChatAnthropic):
    """Create a ReAct agent for general conversation with memory tools."""
    return create_react_agent(
        model=model,
        tools=ALL_MEMORY_TOOLS,
        name="conversation_agent",
        prompt=CONVERSATION_PROMPT,
    )
