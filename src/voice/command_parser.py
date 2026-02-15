"""Voice command parser — converts natural language transcripts into structured intents."""

from __future__ import annotations

import json
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

VOICE_COMMAND_PROMPT = """You parse voice commands for a Git-based conversation system.
Given a voice transcript, determine:
1. intent: one of [chat, checkpoint, time_travel, fork, merge, diff, log, push, issue, pr, gist, list_branches]
2. parameters: extracted from the command

Examples:
- "Save this conversation point" → {"intent": "checkpoint", "params": {"label": "conversation-point"}}
- "Show me the conversation tree" → {"intent": "log", "params": {}}
- "Go back to before I said fifty thousand" → {"intent": "time_travel", "params": {"search_text": "fifty thousand"}}
- "What if I had said seventy five thousand instead" → {"intent": "fork", "params": {"new_input": "seventy five thousand"}}
- "Merge the influencer idea into the main plan" → {"intent": "merge", "params": {"source": "influencer idea"}}
- "Push this to GitHub so the team can see" → {"intent": "push", "params": {}}
- "Create an issue from this point" → {"intent": "issue", "params": {}}
- "Share this conversation" → {"intent": "gist", "params": {}}
- "List all branches" → {"intent": "list_branches", "params": {}}
- "Just chatting" or general questions → {"intent": "chat", "params": {}}

Return JSON only. No markdown fences, no explanation."""

VALID_INTENTS = {
    "chat",
    "checkpoint",
    "time_travel",
    "fork",
    "merge",
    "diff",
    "log",
    "push",
    "issue",
    "pr",
    "gist",
    "list_branches",
}


class VoiceCommandParser:
    """Parses voice transcripts into structured commands using Claude."""

    def __init__(self, model: ChatAnthropic) -> None:
        self.model = model

    async def parse(self, transcript: str) -> dict[str, Any]:
        """Parse a voice transcript into ``{"intent": ..., "params": ...}``."""
        response = await self.model.ainvoke(
            [
                SystemMessage(content=VOICE_COMMAND_PROMPT),
                HumanMessage(content=f"Voice transcript: {transcript}"),
            ]
        )
        return self._extract_json(response.content)

    def parse_sync(self, transcript: str) -> dict[str, Any]:
        """Synchronous version of :meth:`parse`."""
        response = self.model.invoke(
            [
                SystemMessage(content=VOICE_COMMAND_PROMPT),
                HumanMessage(content=f"Voice transcript: {transcript}"),
            ]
        )
        return self._extract_json(response.content)

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extract JSON from the model response, with fallback."""
        text = text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            return {"intent": "chat", "params": {"raw": text}}

        # Validate
        if not isinstance(result, dict) or "intent" not in result:
            return {"intent": "chat", "params": {"raw": text}}

        if result["intent"] not in VALID_INTENTS:
            result["intent"] = "chat"

        result.setdefault("params", {})
        return result
