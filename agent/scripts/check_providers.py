"""Check what this account can really use, before a demo relies on any of it.

    uv run python scripts/check_providers.py

The docs say what exists; this says what works with your keys. It makes one short TTS request per
model and one short STT request per option (a few rupees of credit at most), lists the LLMs your Groq
key can reach, and prints the settings to use. Keys are never printed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx
from audio import frames_of, speech_context, synthesise
from dotenv import load_dotenv
from livekit.agents import stt as lk_stt

from agent.languages import build_hearing, build_voice

SENTENCE = "નમસ્તે! પાણીની સુવિધા વિશે બે મિનિટનો નાનો સર્વે છે. તમારું ગામ કયું છે?"
TTS_OPTIONS = {
    "bulbul:v3 (shubh)": {"SARVAM_TTS_MODEL": "bulbul:v3", "SARVAM_TTS_SPEAKER": "shubh"},
    "bulbul:v4-flash (bhavik_gu_conversation)": {
        "SARVAM_TTS_MODEL": "bulbul:v4-flash",
        "SARVAM_TTS_SPEAKER": "bhavik_gu_conversation",
    },
}
STT_OPTIONS = {
    "saaras:v3 websocket, codemix": {"STT_PROVIDER": "sarvam", "SARVAM_STT_MODEL": "saaras:v3"},
    "saaras:v4 websocket, codemix": {"STT_PROVIDER": "sarvam", "SARVAM_STT_MODEL": "saaras:v4"},
    "saaras:v3-realtime (partial transcripts)": {"STT_PROVIDER": "sarvam-realtime"},
    "deepgram nova-3 gu": {"STT_PROVIDER": "deepgram", "GU_DEEPGRAM_LANGUAGE": "gu"},
}
GROQ_CANDIDATES = ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile")


def show(ok: bool, name: str, detail: str) -> None:
    print(f"  [{'ok' if ok else 'FAIL'}] {name}: {detail}")


async def check_tts() -> object | None:
    print("\nVoices (one Gujarati sentence each)")
    audio = None
    for name, env in TTS_OPTIONS.items():
        os.environ.update(env)
        try:
            voice = build_voice()
            said, first = await synthesise(voice, SENTENCE)
            show(True, name, f"{said.seconds:.1f} s of audio, first audio after {first * 1000:.0f} ms")
            audio = audio or said
        except Exception as e:  # any failure here is the answer the script exists to report
            show(False, name, str(e)[:140])
    return audio


async def transcribe(stt: lk_stt.STT, audio, timeout: float = 20.0) -> tuple[str, float]:
    stream = stt.stream()
    words: list[str] = []
    ended = 0.0

    async def feed() -> None:
        nonlocal ended
        for frame in frames_of(audio):
            stream.push_frame(frame)
            await asyncio.sleep(0.02)
        ended = time.perf_counter()
        silence = type(audio)(bytes(len(audio.pcm) // max(1, round(audio.seconds)) * 2), audio.sample_rate)
        for frame in frames_of(silence):
            stream.push_frame(frame)
            await asyncio.sleep(0.02)
        stream.end_input()

    async def read() -> float:
        async for event in stream:
            if event.type == lk_stt.SpeechEventType.FINAL_TRANSCRIPT and event.alternatives:
                words.append(event.alternatives[0].text)
                return time.perf_counter() - ended
        return 0.0

    feeding = asyncio.create_task(feed())
    try:
        delay = await asyncio.wait_for(read(), timeout)
    finally:
        feeding.cancel()
        await stream.aclose()
    return " ".join(words), delay


async def check_stt(audio) -> None:
    print("\nHearing (the sentence above, as a call would send it)")
    for name, env in STT_OPTIONS.items():
        needs = "DEEPGRAM_API_KEY" if env["STT_PROVIDER"] == "deepgram" else "SARVAM_API_KEY"
        if not os.getenv(needs):
            show(False, name, f"{needs} isn't set")
            continue
        os.environ.update(env)
        try:
            hearing = build_hearing("browser")
            text, delay = await transcribe(hearing.stt, audio)
            partial = "partial transcripts" if hearing.partial_transcripts else "finished sentences only"
            show(bool(text), name, f"{delay * 1000:.0f} ms after speech, {partial}: {text[:70]}")
        except Exception as e:
            show(False, name, str(e)[:140])


def check_llms() -> None:
    print("\nLLMs")
    if key := os.getenv("GROQ_API_KEY"):
        reply = httpx.get(
            "https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=15
        )
        reply.raise_for_status()
        models = {m["id"] for m in reply.json()["data"]}
        for candidate in GROQ_CANDIDATES:
            show(
                candidate in models, candidate, "available" if candidate in models else "not on this account"
            )
    else:
        show(False, "Groq", "GROQ_API_KEY isn't set")
    if key := os.getenv("GOOGLE_API_KEY"):
        reply = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": key},
            params={"pageSize": 200},
            timeout=15,
        )
        reply.raise_for_status()
        flash = sorted(m["name"].split("/")[-1] for m in reply.json()["models"] if "flash" in m["name"])
        show(bool(flash), "Gemini Flash models", ", ".join(flash[:8]))
    else:
        show(False, "Gemini", "GOOGLE_API_KEY isn't set")


async def main() -> int:
    load_dotenv()
    sys.stdout.reconfigure(encoding="utf-8")
    if not os.getenv("SARVAM_API_KEY"):
        print("SARVAM_API_KEY isn't set in agent/.env. dashboard.sarvam.ai -> API keys.")
        return 1
    async with speech_context():
        audio = await check_tts()
        if audio is None:
            print("\nNo voice worked, so hearing can't be tested. Check the key and the credit left.")
            return 1
        await check_stt(audio)
    check_llms()
    print("\nChoose STT_PROVIDER and SARVAM_TTS_MODEL from what passed: see docs/agent.md.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
