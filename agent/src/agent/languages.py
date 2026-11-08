"""The Gujarati speech stack: hearing (STT), the voice (TTS) and turn-taking, set by environment.

Sarvam hears and speaks by default: Saaras in codemix mode keeps English words in English
("પાણી daily આવે છે"), which is how Gujarat talks, and Bulbul speaks Gujarati. Every provider choice
is an environment variable, so comparing two is a config change (scripts/check_providers.py shows
which ones an account can use).
"""

from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass
from typing import Any, Literal

from livekit.agents import inference, stt, tts
from livekit.agents.inference.eot.languages import LOCAL_LANGUAGES
from livekit.plugins import deepgram, sarvam

from agent.gujarati.speech import Gender, speak_gujarati, speak_plain_punctuation

logger = logging.getLogger("agent.languages")

Channel = Literal["phone", "browser"]
LANGUAGE_CODE = "gu-IN"

# Bulbul voices and whether they're male or female, as the Sarvam plugin lists them. Gujarati verbs
# change with the speaker's gender, so the wrong entry here means a voice with the wrong grammar.
MALE_VOICES = {
    "shubh", "rahul", "amit", "ratan", "rohan", "dev", "manan", "sumit", "aditya", "kabir", "varun",
    "aayan", "ashutosh", "advait", "bhavik_gu_conversation",
}  # fmt: skip
FEMALE_VOICES = {
    "ritu", "pooja", "simran", "kavya", "ishita", "shreya", "priya", "neha", "roopa", "amelia", "sophia",
    "suhani", "rupali", "tanya", "shruti", "kavitha", "pooja_gu_conversational", "pooja_gu_customer",
}  # fmt: skip


def _on(name: str, default: str = "off") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "on", "true", "yes")


@dataclass
class Hearing:
    """The speech-to-text for a call, and what the rest of the session needs to know about it."""

    stt: stt.STT
    # Whether it sends words while the person is still talking. LiveKit counts those to decide if
    # they're interrupting; an STT that only sends finished sentences has nothing to count.
    partial_transcripts: bool

    @property
    def interruption(self) -> dict[str, Any]:
        """Only real words stop the agent: "no, wait" (2 words) does, "હં" or a cough doesn't.

        That rule needs partial transcripts. Without them no words arrive until the person has
        finished the sentence, and the agent would talk over them to the end of it. So any speech
        stops it instead, and a false stop (a cough) resumes.
        """
        return {"min_words": 2 if self.partial_transcripts else 0, "resume_false_interruption": True}


class FlushedSarvamSTT(sarvam.STT):
    """Saaras that LiveKit asks for the transcript the moment the person's turn ends, instead of
    waiting for Sarvam's own end-of-speech detection (its documented flush signal).

    Off by default (SARVAM_STT_FLUSH=on turns it on) until it has been tried on live calls: it should
    cut the wait after a short answer, such as a name.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(flush_signal=True, **kwargs)
        self._capabilities = dataclasses.replace(self._capabilities, manual_flush=True)


def _sample_rate(channel: Channel) -> int:
    # Phone audio is 8 kHz whatever we do; Sarvam's guidance is to say so rather than upsample.
    return int(os.getenv("SARVAM_STT_PHONE_SAMPLE_RATE", "8000")) if channel == "phone" else 16000


def _sarvam_websocket_stt(channel: Channel, *, flush: bool = False) -> stt.STT:
    options: dict[str, Any] = {
        "language": LANGUAGE_CODE,
        "model": os.getenv("SARVAM_STT_MODEL", "saaras:v3"),
        # codemix keeps English words in English: "પાણી daily આવે છે".
        "mode": os.getenv("SARVAM_STT_MODE", "codemix"),
        "sample_rate": _sample_rate(channel),
    }
    return FlushedSarvamSTT(**options) if flush else sarvam.STT(**options)


def build_hearing(channel: Channel) -> Hearing:
    # "or", not a getenv default: .env.example leaves this blank, and blank is set, not missing.
    provider = (os.getenv("STT_PROVIDER") or "sarvam").lower()
    if provider == "sarvam":
        # Sends only finished sentences: see Hearing.interruption.
        return Hearing(_sarvam_websocket_stt(channel, flush=_on("SARVAM_STT_FLUSH")), False)
    if provider == "sarvam-realtime":
        realtime = sarvam.STTRealtime(
            language=LANGUAGE_CODE,
            mode=os.getenv("SARVAM_STT_MODE", "codemix"),
            stream_type=os.getenv("SARVAM_STT_STREAM_TYPE", "balanced"),
            sample_rate=_sample_rate(channel),
        )
        # A realtime stream never reconnects by itself, as Sarvam bills per connection. Without a
        # backup, one dropped socket would leave the agent deaf for the rest of the call.
        return Hearing(stt.FallbackAdapter([realtime, _sarvam_websocket_stt(channel)]), True)
    if provider == "deepgram":
        return Hearing(deepgram.STT(model="nova-3", language=os.getenv("GU_DEEPGRAM_LANGUAGE", "gu")), True)
    raise ValueError(f"STT_PROVIDER must be sarvam, sarvam-realtime or deepgram, got {provider!r}")


def sarvam_voice() -> str:
    return os.getenv("SARVAM_TTS_SPEAKER", "shubh").lower()


def build_voice() -> tts.TTS:
    options: dict[str, Any] = {}
    if dictionary := os.getenv("SARVAM_TTS_DICT_ID"):
        options["dict_id"] = dictionary
    return sarvam.TTS(
        target_language_code=LANGUAGE_CODE,
        model=os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"),
        speaker=sarvam_voice(),
        pace=float(os.getenv("SARVAM_TTS_PACE", "1.0")),
        temperature=float(os.getenv("SARVAM_TTS_TEMPERATURE", "0.6")),
        speech_sample_rate=int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "24000")),
        output_audio_codec=os.getenv("SARVAM_TTS_CODEC", "mp3"),
        **options,
    )


def voice_gender() -> Gender:
    """Whether the voice is a man's or a woman's, so any first-person verb can match it."""
    if override := os.getenv("SARVAM_TTS_GENDER"):
        if override.lower() not in ("male", "female"):
            raise ValueError(f"SARVAM_TTS_GENDER must be male or female, got {override!r}")
        return "male" if override.lower() == "male" else "female"
    voice = sarvam_voice()
    if voice in MALE_VOICES:
        return "male"
    if voice in FEMALE_VOICES:
        return "female"
    raise ValueError(f"Set SARVAM_TTS_GENDER: {voice!r} isn't in the voice list in languages.py")


def build_turn_detection() -> Any:
    """LiveKit's audio turn model, which listens for the person sounding finished.

    Gujarati isn't one of its 14 languages, so it runs on Hindi's threshold, the closest it knows
    (GU_TURN_DETECTOR=off compares it with silence alone). It can only make the agent wait longer than
    the endpointing floor, never cut in sooner, and the survey caps that wait (main.py).
    """
    if not _on("GU_TURN_DETECTOR", "on"):
        return "vad"
    # A single number, not {"gu": ...}: it applies whatever language the STT reports for a turn,
    # and a code-mixed turn may come back as English or with no language at all.
    return inference.TurnDetector(unlikely_threshold=LOCAL_LANGUAGES["hi"])


def voice_text_transforms(gender: Gender) -> list[Any]:
    """Applied to the text on its way to the voice: "2 કલાક" is said "બે કલાક". The transcript keeps
    what was written."""
    return ["filter_markdown", "filter_emoji", speak_gujarati(gender), speak_plain_punctuation]
