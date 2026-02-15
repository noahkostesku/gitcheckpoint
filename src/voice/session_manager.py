"""Voice session manager — links voice calls to LangGraph conversation threads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.voice.command_parser import VoiceCommandParser
    from src.voice.tts_service import TTSService


class VoiceSessionManager:
    """Routes voice input through the LangGraph supervisor and returns spoken responses."""

    def __init__(
        self,
        graph_app: Any,
        tts_service: "TTSService",
        command_parser: "VoiceCommandParser",
    ) -> None:
        self.graph = graph_app
        self.tts = tts_service
        self.parser = command_parser
        self.active_sessions: dict[str, str] = {}  # call_id → thread_id

    def register_session(self, call_id: str, thread_id: str | None = None) -> str:
        """Register a new voice session, mapping call_id to a thread."""
        tid = thread_id or call_id
        self.active_sessions[call_id] = tid
        return tid

    def get_thread_id(self, call_id: str) -> str:
        """Get the thread_id for a call, creating one if needed."""
        if call_id not in self.active_sessions:
            self.register_session(call_id)
        return self.active_sessions[call_id]

    def end_session(self, call_id: str) -> None:
        """Remove a session when a call ends."""
        self.active_sessions.pop(call_id, None)

    async def handle_voice_input(
        self, call_id: str, transcript: str
    ) -> tuple[str, str]:
        """Process voice input and return (response_text, audio_path).

        1. Parse the voice command for intent
        2. Route through the LangGraph supervisor
        3. Synthesize the response to speech
        """
        # 1. Parse intent (informational — the supervisor handles routing)
        command = await self.parser.parse(transcript)

        # 2. Get or create thread
        thread_id = self.get_thread_id(call_id)

        # 3. Invoke the supervisor graph
        result = await self.graph.ainvoke(
            {"messages": [{"role": "user", "content": transcript}]},
            {"configurable": {"thread_id": thread_id}},
        )

        # 4. Extract response text
        response_text = result["messages"][-1].content

        # 5. Synthesize to speech
        audio_path = self.tts.synthesize(
            response_text,
            output_path=f"voice_response_{call_id}.wav",
        )

        return response_text, audio_path

    def handle_voice_input_sync(
        self, call_id: str, transcript: str
    ) -> tuple[str, str]:
        """Synchronous version of :meth:`handle_voice_input`.

        Parses command synchronously and invokes the graph synchronously.
        """
        command = self.parser.parse_sync(transcript)
        thread_id = self.get_thread_id(call_id)

        result = self.graph.invoke(
            {"messages": [{"role": "user", "content": transcript}]},
            {"configurable": {"thread_id": thread_id}},
        )

        response_text = result["messages"][-1].content
        audio_path = self.tts.synthesize(
            response_text,
            output_path=f"voice_response_{call_id}.wav",
        )

        return response_text, audio_path
