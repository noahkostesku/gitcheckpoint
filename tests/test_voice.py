"""Tests for the voice layer — real API integrations.

These tests use the actual Smallest.ai and Anthropic API keys from .env.
Set SKIP_VOICE_TESTS=1 to skip when running offline.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from langchain_anthropic import ChatAnthropic

from src.config import Settings
from src.voice.tts_service import TTSService
from src.voice.command_parser import VoiceCommandParser, VALID_INTENTS
from src.voice.atoms_agent import GitCheckpointVoiceAgent
from src.voice.session_manager import VoiceSessionManager

# ---------------------------------------------------------------------------
# Skip if no API keys or explicitly disabled
# ---------------------------------------------------------------------------

def _load_settings() -> Settings:
    """Try to load settings from .env, raising SkipTest if missing."""
    try:
        return Settings()
    except Exception as e:
        pytest.skip(f"Cannot load settings: {e}")


def _skip_if_no_voice():
    if os.environ.get("SKIP_VOICE_TESTS", ""):
        pytest.skip("SKIP_VOICE_TESTS is set")


def _skip_if_no_smallestai():
    try:
        import smallestai  # noqa: F401
    except ImportError:
        pytest.skip("smallestai not installed")


# ---------------------------------------------------------------------------
# TTSService
# ---------------------------------------------------------------------------

class TestTTSService:
    @pytest.fixture(autouse=True)
    def setup(self):
        _skip_if_no_voice()
        _skip_if_no_smallestai()
        self.settings = _load_settings()

    def test_init(self):
        tts = TTSService(self.settings)
        assert tts.client is not None
        assert tts.voice_id == self.settings.voice_id

    def test_synthesize_to_file(self):
        tts = TTSService(self.settings)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out = f.name
        try:
            result = tts.synthesize("Hello from GitCheckpoint.", output_path=out)
            assert os.path.exists(result)
            assert os.path.getsize(result) > 0
        finally:
            os.unlink(out)

    def test_synthesize_bytes(self):
        tts = TTSService(self.settings)
        audio = tts.synthesize_bytes("Testing one two three.")
        assert isinstance(audio, bytes)
        assert len(audio) > 100  # Should be meaningful audio data

    @pytest.mark.xfail(reason="Streaming WebSocket API may not support all voice IDs")
    def test_stream_synthesis_from_text(self):
        tts = TTSService(self.settings)
        chunks = list(tts.stream_synthesis_from_text("Stream test."))
        assert len(chunks) > 0
        total_bytes = sum(len(c) for c in chunks)
        assert total_bytes > 0


# ---------------------------------------------------------------------------
# VoiceCommandParser
# ---------------------------------------------------------------------------

class TestVoiceCommandParser:
    @pytest.fixture(autouse=True)
    def setup(self):
        _skip_if_no_voice()
        self.settings = _load_settings()
        self.model = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=self.settings.anthropic_api_key,
        )
        self.parser = VoiceCommandParser(self.model)

    def test_parse_checkpoint_command(self):
        result = self.parser.parse_sync("Save this conversation point")
        assert result["intent"] == "checkpoint"
        assert "params" in result

    def test_parse_log_command(self):
        result = self.parser.parse_sync("Show me the conversation history")
        assert result["intent"] == "log"

    def test_parse_time_travel(self):
        result = self.parser.parse_sync("Go back to before we discussed the budget")
        assert result["intent"] == "time_travel"

    def test_parse_fork_command(self):
        result = self.parser.parse_sync("What if I had said a million dollars instead")
        assert result["intent"] == "fork"

    def test_parse_push_command(self):
        result = self.parser.parse_sync("Push this conversation to GitHub")
        assert result["intent"] == "push"

    def test_parse_chat_command(self):
        result = self.parser.parse_sync("What is the capital of France?")
        assert result["intent"] == "chat"

    def test_parse_gist_command(self):
        result = self.parser.parse_sync("Share this as a gist")
        assert result["intent"] == "gist"

    def test_parse_list_branches(self):
        result = self.parser.parse_sync("List all conversation branches")
        assert result["intent"] == "list_branches"

    def test_parse_always_returns_valid_intent(self):
        result = self.parser.parse_sync("asdf gibberish xyz")
        assert result["intent"] in VALID_INTENTS


# ---------------------------------------------------------------------------
# VoiceCommandParser — JSON extraction unit tests (no API)
# ---------------------------------------------------------------------------

class TestCommandParserExtractJson:
    """Test the _extract_json method without API calls."""

    @pytest.fixture(autouse=True)
    def setup(self):
        # Use None as model — we only test _extract_json, never invoke the model
        self.parser = VoiceCommandParser(None)  # type: ignore[arg-type]

    def test_plain_json(self):
        result = self.parser._extract_json('{"intent": "checkpoint", "params": {}}')
        assert result["intent"] == "checkpoint"

    def test_json_with_fences(self):
        text = '```json\n{"intent": "log", "params": {}}\n```'
        result = self.parser._extract_json(text)
        assert result["intent"] == "log"

    def test_invalid_json_falls_back(self):
        result = self.parser._extract_json("not json at all")
        assert result["intent"] == "chat"
        assert "raw" in result["params"]

    def test_missing_intent_falls_back(self):
        result = self.parser._extract_json('{"action": "something"}')
        assert result["intent"] == "chat"

    def test_invalid_intent_normalised(self):
        result = self.parser._extract_json('{"intent": "invalid_thing", "params": {}}')
        assert result["intent"] == "chat"

    def test_params_default(self):
        result = self.parser._extract_json('{"intent": "push"}')
        assert result["params"] == {}


# ---------------------------------------------------------------------------
# GitCheckpointVoiceAgent (Atoms)
# ---------------------------------------------------------------------------

class TestAtomsAgent:
    @pytest.fixture(autouse=True)
    def setup(self):
        _skip_if_no_voice()
        _skip_if_no_smallestai()
        self.settings = _load_settings()

    def test_init(self):
        agent = GitCheckpointVoiceAgent(self.settings)
        assert agent.client is not None


# ---------------------------------------------------------------------------
# VoiceSessionManager
# ---------------------------------------------------------------------------

class TestVoiceSessionManager:
    def test_register_and_get_session(self):
        manager = VoiceSessionManager(
            graph_app=None, tts_service=None, command_parser=None
        )
        tid = manager.register_session("call-123", "my-thread")
        assert tid == "my-thread"
        assert manager.get_thread_id("call-123") == "my-thread"

    def test_auto_create_session(self):
        manager = VoiceSessionManager(
            graph_app=None, tts_service=None, command_parser=None
        )
        tid = manager.get_thread_id("call-456")
        assert tid == "call-456"
        assert "call-456" in manager.active_sessions

    def test_end_session(self):
        manager = VoiceSessionManager(
            graph_app=None, tts_service=None, command_parser=None
        )
        manager.register_session("call-789")
        manager.end_session("call-789")
        assert "call-789" not in manager.active_sessions

    def test_end_nonexistent_session_is_noop(self):
        manager = VoiceSessionManager(
            graph_app=None, tts_service=None, command_parser=None
        )
        manager.end_session("ghost")  # should not raise

    def test_default_thread_id_is_call_id(self):
        manager = VoiceSessionManager(
            graph_app=None, tts_service=None, command_parser=None
        )
        tid = manager.register_session("call-abc")
        assert tid == "call-abc"
