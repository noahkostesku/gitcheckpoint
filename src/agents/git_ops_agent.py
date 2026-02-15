"""Git operations agent — handles local git operations on conversation state."""

from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

GIT_OPS_PROMPT = (
    "You are the Git Operations specialist for GitCheckpoint. "
    "You handle: saving checkpoints, time-traveling to past states, "
    "forking conversations into branches, merging branches, showing diffs "
    "between checkpoints, and displaying the conversation tree/log. "
    "Always confirm operations with clear, concise descriptions of what happened. "
    "Use commit SHAs when referencing specific points."
)


def create_git_ops_agent(model: ChatAnthropic, git_tools: list):
    """Create a ReAct agent for git operations on conversations."""
    return create_react_agent(
        model=model,
        tools=git_tools,
        name="git_ops_agent",
        prompt=GIT_OPS_PROMPT,
    )
