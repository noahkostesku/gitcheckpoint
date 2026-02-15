"""Atoms agent — configures a Smallest.ai voice agent for GitCheckpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

try:
    from smallestai import AtomsClient, Configuration
    from smallestai.atoms.models.create_agent_request import CreateAgentRequest
    from smallestai.atoms.models.create_agent_request_language import (
        CreateAgentRequestLanguage,
    )
    from smallestai.atoms.models.create_agent_request_language_synthesizer import (
        CreateAgentRequestLanguageSynthesizer,
    )
    from smallestai.atoms.models.create_agent_request_language_synthesizer_voice_config import (
        CreateAgentRequestLanguageSynthesizerVoiceConfig,
    )

    ATOMS_AVAILABLE = True
except ImportError:
    ATOMS_AVAILABLE = False

if TYPE_CHECKING:
    from src.config import Settings


class GitCheckpointVoiceAgent:
    """Manages an Atoms voice agent for GitCheckpoint conversations."""

    def __init__(self, settings: "Settings") -> None:
        if not ATOMS_AVAILABLE:
            raise ImportError(
                "smallestai is required for Atoms voice agents. "
                "Install with: pip install smallestai"
            )

        config = Configuration(access_token=settings.smallest_api_key)
        self.client = AtomsClient(configuration=config)
        self.agent_id: str | None = settings.atoms_agent_id or None

    def create_agent(self) -> str:
        """Create the GitCheckpoint Atoms voice agent and return its ID."""
        request = CreateAgentRequest(
            name="GitCheckpoint Voice Agent",
            description="Version control for conversations via voice",
            language=CreateAgentRequestLanguage(
                enabled="en",
                switching=False,
                synthesizer=CreateAgentRequestLanguageSynthesizer(
                    voice_config=CreateAgentRequestLanguageSynthesizerVoiceConfig(
                        model="waves_lightning_large",
                        voice_id="emily",
                    ),
                    speed=1.1,
                    consistency=0.5,
                    similarity=0,
                    enhancement=1,
                ),
            ),
            slm_model="electron",
            global_prompt=(
                "You are GitCheckpoint, a voice-enabled AI assistant that "
                "version-controls conversations like Git repositories. "
                "You can save checkpoints, rewind, fork, merge, and share "
                "conversations. Be concise and conversational."
            ),
        )
        response = self.client.create_agent(create_agent_request=request)
        self.agent_id = response.data
        return self.agent_id

    def get_agent_id(self) -> str | None:
        """Return the current agent ID (None if not created)."""
        return self.agent_id

    def delete_agent(self) -> None:
        """Delete the current agent."""
        if self.agent_id:
            self.client.delete_agent(id=self.agent_id)
            self.agent_id = None
