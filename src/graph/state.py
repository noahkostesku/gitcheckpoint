"""Shared conversation state schema for the GitCheckpoint supervisor graph."""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ConversationState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    current_thread_id: str
    current_checkpoint_id: str | None
    active_branches: list[str]
    last_git_operation: str | None
    voice_enabled: bool
