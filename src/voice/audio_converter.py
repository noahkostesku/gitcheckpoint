"""WebM-to-WAV audio conversion for browser-recorded audio."""

from __future__ import annotations

import io
import logging
import subprocess
import tempfile

logger = logging.getLogger("gitcheckpoint")


async def webm_to_wav(webm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Convert WebM/Opus audio bytes to WAV (PCM 16-bit mono).

    Uses ffmpeg if available, otherwise falls back to pydub.
    """
    if not webm_bytes:
        return b""

    # Try ffmpeg first (fastest, most reliable)
    try:
        return await _ffmpeg_convert(webm_bytes, sample_rate)
    except (FileNotFoundError, OSError):
        pass

    # Fallback: pydub
    try:
        return _pydub_convert(webm_bytes, sample_rate)
    except ImportError:
        logger.error("Neither ffmpeg nor pydub available for audio conversion")
        raise RuntimeError(
            "Audio conversion requires ffmpeg or pydub. "
            "Install ffmpeg or run: pip install pydub"
        )


async def _ffmpeg_convert(webm_bytes: bytes, sample_rate: int) -> bytes:
    """Convert using ffmpeg subprocess."""
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i", "pipe:0",
        "-f", "wav",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=webm_bytes)
    if proc.returncode != 0:
        raise OSError(f"ffmpeg failed: {stderr.decode()[:200]}")
    return stdout


def _pydub_convert(webm_bytes: bytes, sample_rate: int) -> bytes:
    """Convert using pydub (requires ffmpeg backend)."""
    from pydub import AudioSegment

    audio = AudioSegment.from_file(io.BytesIO(webm_bytes), format="webm")
    audio = audio.set_frame_rate(sample_rate).set_channels(1).set_sample_width(2)

    buf = io.BytesIO()
    audio.export(buf, format="wav")
    return buf.getvalue()
