"""Which language a call is in, and the speech stack that goes with it.

AGENT_LANGUAGE=en (the default) is the Deepgram stack the agent has always had. AGENT_LANGUAGE=gu is
Sarvam for hearing and speaking, with the Gujarati lines, prompt and rules around it. Every provider
choice is an environment variable, so comparing two of them is a config change: see
docs/gujarati/README.md for the options and agent/scripts/gujarati/ for the comparisons.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from livekit.agents import inference, stt, tts
from livekit.agents.inference.eot.languages import LOCAL_LANGUAGES
from livekit.plugins import deepgram, sarvam

from agent.gujarati.lines import Gender
from agent.gujarati.speech import speak_gujarati
from agent.speakable import speak_numbers_digit_by_digit, speak_plain_punctuation

logger = logging.getLogger("agent.languages")

Channel = Literal["phone", "browser", "telegram"]
LANGUAGES = ("en", "gu")
SARVAM_LANGUAGE_CODE = {"en": "en-IN", "gu": "gu-IN"}

# Terms in Sarvam's realtime prompt. It takes free text, and a long one is untested.
MAX_PROMPT_TERMS = 40

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


def agent_language() -> str:
    language = os.getenv("AGENT_LANGUAGE", "en").lower()
    if language not in LANGUAGES:
        raise ValueError(f"AGENT_LANGUAGE must be one of {', '.join(LANGUAGES)}, got {language!r}")
    return language


@dataclass
class Hearing:
    """The speech-to-text for a call, and what the rest of the session needs to know about it."""

    stt: stt.STT
    # Whether it sends words while the caller is still talking. LiveKit counts those to decide if the
    # caller is interrupting; an STT that only sends finished sentences has nothing to count.
    partial_transcripts: bool
    learn: Callable[[list[str]], None]  # teach it the restaurant's dish and street names

    @property
    def interruption(self) -> dict[str, Any]:
        """Only real words stop the agent: "no, wait" (2 words) does, "mm-hmm" or a cough doesn't.

        That rule needs partial transcripts. Without them no words arrive until the caller has
        finished the sentence, and the agent would talk over them to the end of it. So any speech
        stops it instead, and a false stop (a cough) resumes.
        """
        return {"min_words": 2 if self.partial_transcripts else 0, "resume_false_interruption": True}


def _sarvam_sample_rate(channel: Channel) -> int:
    # Phone audio is 8 kHz whatever we do; Sarvam's guidance is to say so rather than upsample.
    return int(os.getenv("SARVAM_STT_PHONE_SAMPLE_RATE", "8000")) if channel == "phone" else 16000


def _sarvam_websocket_stt(language: str, channel: Channel) -> stt.STT:
    return sarvam.STT(
        language=SARVAM_LANGUAGE_CODE[language],
        model=os.getenv("SARVAM_STT_MODEL", "saaras:v3"),
        # codemix keeps English words in English: "હું office માં છું", which is how Gujarat talks.
        mode=os.getenv("SARVAM_STT_MODE", "codemix"),
        sample_rate=_sarvam_sample_rate(channel),
    )


def build_hearing(language: str, channel: Channel) -> Hearing:
    default = "sarvam" if language == "gu" else "deepgram"
    # "or", not a getenv default: .env.example leaves this blank, and blank is set, not missing.
    provider = (os.getenv("STT_PROVIDER") or default).lower()
    if provider == "deepgram":
        code = (
            os.getenv("GU_DEEPGRAM_LANGUAGE", "gu")
            if language == "gu"
            # en-US by default: on Indian-accented test calls (2 Nov 2026) it matched en-IN and beat
            # "multi", which garbled English names; see docs/agent.md before changing it.
            else os.getenv("STT_LANGUAGE", "en-US")
        )
        deepgram_stt = deepgram.STT(model="nova-3", language=code)
        return Hearing(deepgram_stt, True, lambda terms: deepgram_stt.update_options(keyterm=terms))
    if provider == "sarvam":
        # The plugin takes no term list for saaras:v3 or v4, and sends only finished sentences.
        return Hearing(_sarvam_websocket_stt(language, channel), False, lambda _terms: None)
    if provider == "sarvam-realtime":
        realtime = sarvam.STTRealtime(
            language=SARVAM_LANGUAGE_CODE[language],
            mode=os.getenv("SARVAM_STT_MODE", "codemix"),
            stream_type=os.getenv("SARVAM_STT_STREAM_TYPE", "balanced"),
            sample_rate=_sarvam_sample_rate(channel),
        )

        def learn(terms: list[str]) -> None:
            realtime.update_options(prompt=", ".join(terms[:MAX_PROMPT_TERMS]))

        # A realtime stream never reconnects by itself, as Sarvam bills per connection. Without a
        # backup, one dropped socket would leave the agent deaf for the rest of the call.
        backup = _sarvam_websocket_stt(language, channel)
        return Hearing(stt.FallbackAdapter([realtime, backup]), True, learn)
    raise ValueError(f"STT_PROVIDER must be deepgram, sarvam or sarvam-realtime, got {provider!r}")


def sarvam_voice() -> str:
    return os.getenv("SARVAM_TTS_SPEAKER", "shubh").lower()


def build_voice(language: str) -> tts.TTS:
    default = "sarvam" if language == "gu" else "deepgram"
    provider = (os.getenv("TTS_PROVIDER") or default).lower()
    if provider == "deepgram":
        if language == "gu":
            raise ValueError("Gujarati needs TTS_PROVIDER=sarvam: TTS_VOICE is an English Aura voice")
        return deepgram.TTS(model=os.getenv("TTS_VOICE", "aura-2-andromeda-en"))
    if provider != "sarvam":
        raise ValueError(f"TTS_PROVIDER must be deepgram or sarvam, got {provider!r}")
    options: dict[str, Any] = {}
    if dictionary := os.getenv("SARVAM_TTS_DICT_ID"):
        options["dict_id"] = dictionary
    return sarvam.TTS(
        target_language_code=SARVAM_LANGUAGE_CODE[language],
        model=os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"),
        speaker=sarvam_voice(),
        pace=float(os.getenv("SARVAM_TTS_PACE", "1.0")),
        temperature=float(os.getenv("SARVAM_TTS_TEMPERATURE", "0.6")),
        speech_sample_rate=int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "24000")),
        output_audio_codec=os.getenv("SARVAM_TTS_CODEC", "mp3"),
        **options,
    )


def voice_gender() -> Gender:
    """Whether the voice is a man's or a woman's, so the LLM's grammar can match it."""
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


def build_turn_detection(language: str) -> Any:
    """LiveKit's audio turn model, which listens for the caller sounding finished.

    Gujarati isn't one of its 14 languages. It runs anyway, on a default threshold tuned for English.
    Hindi is the closest language it knows, so Gujarati gets Hindi's threshold: an assumption until
    real calls test it (GU_TURN_DETECTOR=off compares). It can only make the agent wait longer than
    the floors in turn_taking.GUJARATI, never cut in sooner.
    """
    if language != "gu":
        return inference.TurnDetector()
    if os.getenv("GU_TURN_DETECTOR", "on").lower() == "off":
        return "vad"
    # A single number, not {"gu": ...}: it applies whatever language the STT reports for a turn,
    # and a code-mixed turn may come back as English or with no language at all.
    return inference.TurnDetector(unlikely_threshold=LOCAL_LANGUAGES["hi"])


def voice_text_transforms(language: str, gender: Gender) -> list[Any]:
    """Applied to the text on its way to the voice. The transcript keeps what the LLM wrote."""
    if language == "gu":
        return ["filter_markdown", "filter_emoji", speak_gujarati(gender), speak_plain_punctuation]
    # Plain punctuation for the voice, and phone numbers read digit by digit even when the LLM
    # writes "9876543210".
    return ["filter_markdown", "filter_emoji", speak_plain_punctuation, speak_numbers_digit_by_digit]
