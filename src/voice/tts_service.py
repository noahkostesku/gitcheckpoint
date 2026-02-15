"""Waves TTS service — text-to-speech via Smallest.ai Lightning model."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

try:
    from smallestai import WavesClient, AsyncWavesClient, WavesStreamingTTS
    from smallestai.waves.stream_tts import TTSConfig

    SMALLESTAI_AVAILABLE = True
except ImportError:
    SMALLESTAI_AVAILABLE = False

if TYPE_CHECKING:
    from src.config import Settings


class TTSService:
    """Synchronous + streaming text-to-speech via Smallest.ai Waves."""

    def __init__(self, settings: "Settings") -> None:
        if not SMALLESTAI_AVAILABLE:
            raise ImportError(
                "smallestai is required for TTS. Install with: pip install smallestai"
            )

        self.api_key = settings.smallest_api_key
        self.voice_id = settings.voice_id
        self.sample_rate = settings.voice_sample_rate
        self.model = settings.voice_model

        self.client = WavesClient(
            api_key=self.api_key,
            model=self.model,
            sample_rate=self.sample_rate,
            voice_id=self.voice_id,
        )
        self.async_client = AsyncWavesClient(
            api_key=self.api_key,
            model=self.model,
            sample_rate=self.sample_rate,
            voice_id=self.voice_id,
        )

    def synthesize(self, text: str, output_path: str = "output.wav") -> str:
        """Synthesize text to an audio file.

        Returns the path to the written file.
        """
        audio_bytes = self.client.synthesize(text)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return output_path

    def synthesize_bytes(self, text: str) -> bytes:
        """Synthesize text and return raw audio bytes."""
        return self.client.synthesize(text)

    async def async_synthesize_bytes(self, text: str) -> bytes:
        """Async version of synthesize_bytes."""
        return await self.async_client.synthesize(text)

    def stream_synthesis(
        self, text_stream: Generator[str, None, None]
    ) -> Generator[bytes, None, None]:
        """Stream TTS from a text generator.

        Yields audio chunks as they are produced.
        """
        tts_config = TTSConfig(
            voice_id=self.voice_id,
            api_key=self.api_key,
            sample_rate=self.sample_rate,
        )
        streamer = WavesStreamingTTS(config=tts_config)
        yield from streamer.synthesize_streaming(text_stream)

    def stream_synthesis_from_text(self, text: str) -> Generator[bytes, None, None]:
        """Stream TTS from a single text string.

        Yields audio chunks as they are produced.
        """
        tts_config = TTSConfig(
            voice_id=self.voice_id,
            api_key=self.api_key,
            sample_rate=self.sample_rate,
        )
        streamer = WavesStreamingTTS(config=tts_config)
        yield from streamer.synthesize(text)
