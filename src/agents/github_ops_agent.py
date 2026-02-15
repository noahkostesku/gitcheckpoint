"""GitHub operations agent — handles remote GitHub operations."""

from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

GITHUB_OPS_PROMPT = (
    "You are the GitHub Integration specialist for GitCheckpoint. "
    "You handle: pushing conversation branches to GitHub, creating issues "
    "from interesting conversation checkpoints, opening PRs for conversation "
    "reviews, and sharing conversation transcripts as GitHub Gists. "
    "Always provide links to created GitHub resources."
)


def create_github_ops_agent(model: ChatAnthropic, github_tools: list):
    """Create a ReAct agent for GitHub integration."""
    return create_react_agent(
        model=model,
        tools=github_tools,
        name="github_ops_agent",
        prompt=GITHUB_OPS_PROMPT,
    )
