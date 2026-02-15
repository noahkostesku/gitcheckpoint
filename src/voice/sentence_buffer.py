"""Sentence-level buffering for streaming TTS synthesis."""

from __future__ import annotations


class SentenceBuffer:
    """Accumulates streaming text tokens and yields complete sentences.

    Used to split LLM streaming output into sentence-sized chunks
    for TTS synthesis, so the first audio plays before the full
    response is generated.
    """

    ENDINGS = ".!?:;"
    MIN_LENGTH = 10

    def __init__(self) -> None:
        self._buffer = ""

    def add_token(self, token: str) -> list[str]:
        """Add a token and return any complete sentences."""
        self._buffer += token
        sentences: list[str] = []

        while True:
            # Find the earliest sentence-ending character
            best = -1
            for ch in self.ENDINGS:
                idx = self._buffer.find(ch)
                if idx != -1 and (best == -1 or idx < best):
                    best = idx

            if best == -1:
                break

            candidate = self._buffer[: best + 1].strip()
            self._buffer = self._buffer[best + 1 :]

            if len(candidate) >= self.MIN_LENGTH:
                sentences.append(candidate)
            elif candidate:
                # Too short — prepend back to buffer
                self._buffer = candidate + " " + self._buffer

        return sentences

    def flush(self) -> str | None:
        """Return any remaining text in the buffer."""
        remaining = self._buffer.strip()
        self._buffer = ""
        return remaining if remaining else None
