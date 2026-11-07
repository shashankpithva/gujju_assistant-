"""Shared by the Gujarati audio scripts: run the agent's own STT and TTS, and handle WAV files.

The scripts build their voice and STT with languages.py, so what's measured is the configuration a
real call would use, not a copy of it.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import time
import wave
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # evals/ is imported from here, and isn't an installed package
CACHE = ROOT / ".cache/gujarati"


@dataclass
class Audio:
    pcm: bytes
    sample_rate: int

    @property
    def seconds(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate


def save_wav(audio: Audio, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(audio.sample_rate)
        out.writeframes(audio.pcm)


def load_wav(path: Path) -> Audio:
    """16-bit mono WAV, as the recording instructions ask for."""
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError(f"{path}: needs 16-bit mono (use ffmpeg -ac 1 -sample_fmt s16)")
        return Audio(source.readframes(source.getnframes()), source.getframerate())


def phone_copy(source: Path, target: Path) -> Path:
    """What a caller actually hears: 8 kHz G.711 mu-law, the codec of an ordinary phone line.

    Judging a voice from studio-quality audio tells you little about a phone call: everything above
    about 3.4 kHz is gone, and with it much of what separates "સ" from "શ". The result is a WAV again
    so a browser can play it, but the damage is in the sound.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg isn't on the PATH: it's needed to make the phone-quality copy")
    target.parent.mkdir(parents=True, exist_ok=True)
    narrow = ["-af", "highpass=f=300,lowpass=f=3400", "-ar", "8000", "-ac", "1"]
    mulaw = target.with_suffix(".mulaw.wav")
    run = ["ffmpeg", "-y", "-loglevel", "error"]
    subprocess.run([*run, "-i", str(source), *narrow, "-c:a", "pcm_mulaw", str(mulaw)], check=True)
    subprocess.run([*run, "-i", str(mulaw), "-c:a", "pcm_s16le", str(target)], check=True)
    mulaw.unlink()
    return target


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


def require(*names: str) -> None:
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        sys.exit(f"Set {', '.join(missing)} in agent/.env first.")
