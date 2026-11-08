"""For scripts/check_providers.py: run the agent's own STT and TTS on a sample sentence.

The script builds its voice and STT with languages.py, so what's checked is the configuration a real
call would use, not a copy of it.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass


@dataclass
class Audio:
    pcm: bytes
    sample_rate: int

    @property
    def seconds(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate


@contextlib.asynccontextmanager
async def speech_context() -> AsyncIterator[None]:
    """The HTTP session LiveKit plugins expect, which a real call gets from its job."""
    from livekit.agents import utils

    utils.http_context._new_session_ctx()
    try:
        yield
    finally:
        await utils.http_context._close_http_ctx()


async def synthesise(voice, text: str) -> tuple[Audio, float]:
    """The voice saying `text`, and the seconds until its first audio."""
    from livekit import rtc

    started = time.perf_counter()
    first = None
    frames = []
    async with voice.synthesize(text) as stream:
        async for event in stream:
            first = first or time.perf_counter() - started
            frames.append(event.frame)
    merged = rtc.combine_audio_frames(frames)
    return Audio(bytes(merged.data), merged.sample_rate), first or 0.0


def frames_of(audio: Audio, milliseconds: int = 20) -> Iterator:
    from livekit import rtc

    samples = audio.sample_rate * milliseconds // 1000
    size = samples * 2
    for start in range(0, len(audio.pcm) - size + 1, size):
        yield rtc.AudioFrame(audio.pcm[start : start + size], audio.sample_rate, 1, samples)
