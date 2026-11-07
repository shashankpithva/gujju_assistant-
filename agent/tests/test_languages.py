"""Choosing the speech stack: no network, only that each combination builds and says what it can do."""

import pytest
from livekit.agents import stt
from livekit.plugins import deepgram, sarvam

from agent.languages import (
    FEMALE_VOICES,
    MALE_VOICES,
    agent_language,
    build_hearing,
    build_turn_detection,
    build_voice,
    voice_gender,
    voice_text_transforms,
)


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "test")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test")
    monkeypatch.setenv("LIVEKIT_URL", "wss://test.livekit.cloud")
    for name in (
        "AGENT_LANGUAGE", "STT_PROVIDER", "TTS_PROVIDER", "SARVAM_STT_MODEL", "SARVAM_STT_MODE",
        "SARVAM_TTS_MODEL", "SARVAM_TTS_SPEAKER", "SARVAM_TTS_GENDER", "GU_TURN_DETECTOR", "STT_LANGUAGE",
    ):  # fmt: skip
        monkeypatch.delenv(name, raising=False)


def test_english_stays_the_default_on_deepgram():
    assert agent_language() == "en"
    hearing = build_hearing("en", "phone")
    assert isinstance(hearing.stt, deepgram.STT)
    assert hearing.interruption == {"min_words": 2, "resume_false_interruption": True}
    assert isinstance(build_voice("en"), deepgram.TTS)


def test_an_unknown_language_is_refused(monkeypatch):
    monkeypatch.setenv("AGENT_LANGUAGE", "fr")
    with pytest.raises(ValueError, match="AGENT_LANGUAGE"):
        agent_language()


def test_gujarati_defaults_to_sarvam_in_codemix_mode():
    hearing = build_hearing("gu", "browser")
    assert isinstance(hearing.stt, sarvam.STT)
    assert hearing.stt._opts.model == "saaras:v3"
    assert hearing.stt._opts.mode == "codemix"
    assert hearing.stt._opts.language.language == "gu"
    assert hearing.stt._opts.sample_rate == 16000


def test_phone_audio_is_declared_as_8_khz():
    assert build_hearing("gu", "phone").stt._opts.sample_rate == 8000
    assert build_hearing("gu", "telegram").stt._opts.sample_rate == 16000


def test_an_stt_that_only_sends_finished_sentences_is_interrupted_by_any_speech():
    """Counting words would leave the agent talking until the caller had finished their sentence."""
    hearing = build_hearing("gu", "phone")
    assert hearing.partial_transcripts is False
    assert hearing.interruption == {"min_words": 0, "resume_false_interruption": True}


def test_sarvam_realtime_counts_words_and_has_a_backup(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "sarvam-realtime")
    hearing = build_hearing("gu", "phone")
    assert isinstance(hearing.stt, stt.FallbackAdapter)
    assert hearing.interruption["min_words"] == 2
    primary, backup = hearing.stt._stt_instances
    assert isinstance(primary, sarvam.STTRealtime) and isinstance(backup, sarvam.STT)


def test_sarvam_realtime_learns_terms_through_its_prompt(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "sarvam-realtime")
    hearing = build_hearing("gu", "phone")
    hearing.learn(["Paneer Tikka", "Swiggy"])
    assert hearing.stt._stt_instances[0]._opts.prompt == "Paneer Tikka, Swiggy"


def test_the_websocket_stt_ignores_terms_instead_of_failing():
    """Deepgram's keyterm option doesn't exist here: passing it on would crash the call."""
    build_hearing("gu", "phone").learn(["Paneer Tikka"])


def test_deepgram_stays_available_for_gujarati(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    monkeypatch.setenv("STT_LANGUAGE", "en-US")  # from .env.example: must not leak into a Gujarati call
    hearing = build_hearing("gu", "phone")
    assert isinstance(hearing.stt, deepgram.STT)
    assert hearing.stt._opts.language.language == "gu"
    assert hearing.interruption["min_words"] == 2  # Deepgram sends partial transcripts


def test_an_unknown_stt_provider_is_refused(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "whisper")
    with pytest.raises(ValueError, match="STT_PROVIDER"):
        build_hearing("gu", "phone")


def test_gujarati_voice_defaults_to_bulbul_v3():
    voice = build_voice("gu")
    assert isinstance(voice, sarvam.TTS)
    assert voice._opts.model == "bulbul:v3"
    assert voice._opts.target_language_code == "gu-IN"
    assert voice._opts.speaker == "shubh"


def test_the_gujarati_personas_of_bulbul_v4_flash_are_accepted(monkeypatch):
    monkeypatch.setenv("SARVAM_TTS_MODEL", "bulbul:v4-flash")
    monkeypatch.setenv("SARVAM_TTS_SPEAKER", "bhavik_gu_conversation")
    assert build_voice("gu")._opts.speaker == "bhavik_gu_conversation"
    assert voice_gender() == "male"


def test_deepgram_cant_voice_gujarati(monkeypatch):
    monkeypatch.setenv("TTS_PROVIDER", "deepgram")
    with pytest.raises(ValueError, match="TTS_PROVIDER=sarvam"):
        build_voice("gu")


@pytest.mark.parametrize(
    ("voice", "gender"),
    [("shubh", "male"), ("manan", "male"), ("priya", "female"), ("pooja_gu_customer", "female")],
)
def test_voice_gender_follows_the_voice(monkeypatch, voice, gender):
    monkeypatch.setenv("SARVAM_TTS_SPEAKER", voice)
    assert voice_gender() == gender


def test_a_voice_of_unknown_gender_must_be_declared(monkeypatch):
    monkeypatch.setenv("SARVAM_TTS_SPEAKER", "brandnew")
    with pytest.raises(ValueError, match="SARVAM_TTS_GENDER"):
        voice_gender()
    monkeypatch.setenv("SARVAM_TTS_GENDER", "female")
    assert voice_gender() == "female"


def test_the_voice_lists_match_the_plugin():
    """A plugin upgrade that moves a voice would otherwise give it the wrong grammar, silently."""
    from livekit.plugins.sarvam import models

    table = next(
        v for k, v in vars(models).items() if k.isupper() and isinstance(v, dict) and "bulbul:v3" in v
    )
    assert set(table["bulbul:v3"]["male"]) <= MALE_VOICES
    assert set(table["bulbul:v3"]["female"]) <= FEMALE_VOICES
    assert not MALE_VOICES & FEMALE_VOICES


def test_gujarati_turn_detection_uses_hindis_threshold():
    from livekit.agents.inference.eot.languages import LOCAL_LANGUAGES
    from livekit.agents.language import LanguageCode

    thresholds = build_turn_detection("gu")._opts.thresholds
    # Whatever language the STT reports for a turn, including none.
    for language in (LanguageCode("gu-IN"), LanguageCode("en-IN"), None):
        assert thresholds.lookup(language) == LOCAL_LANGUAGES["hi"]


def test_the_turn_detector_can_be_switched_off_to_compare(monkeypatch):
    monkeypatch.setenv("GU_TURN_DETECTOR", "off")
    assert build_turn_detection("gu") == "vad"


def test_each_language_has_its_own_voice_text_steps():
    assert voice_text_transforms("en", "male")[:2] == ["filter_markdown", "filter_emoji"]
    gujarati = voice_text_transforms("gu", "female")
    assert len(gujarati) == 4 and callable(gujarati[2])


@pytest.mark.parametrize("provider", ["sarvam", "sarvam-realtime", "deepgram"])
@pytest.mark.parametrize("detector", ["on", "off"])
async def test_a_gujarati_session_builds_with_the_options_main_gives_it(monkeypatch, provider, detector):
    """main.py's session, assembled the same way. Only a real call runs it, so nothing else would
    notice LiveKit refusing one of these options."""
    from livekit.agents import AgentSession, TurnHandlingOptions

    from agent.turn_taking import GUJARATI

    monkeypatch.setenv("STT_PROVIDER", provider)
    monkeypatch.setenv("GU_TURN_DETECTOR", detector)
    hearing = build_hearing("gu", "phone")
    session = AgentSession(
        stt=hearing.stt,
        tts=build_voice("gu"),
        turn_handling=TurnHandlingOptions(
            turn_detection=build_turn_detection("gu"),
            endpointing=GUJARATI.quick,
            preemptive_generation={"max_retries": 1, "preemptive_tts": True},
            interruption=hearing.interruption,
        ),
        tts_text_transforms=voice_text_transforms("gu", voice_gender()),
        max_tool_steps=3,
    )
    assert session.options.interruption["min_words"] == hearing.interruption["min_words"]
    assert session.options.endpointing["min_delay"] == GUJARATI.quick["min_delay"]


@pytest.mark.parametrize("language", ["en", "gu"])
def test_a_copy_of_env_example_works_as_it_stands(monkeypatch, language):
    """The first thing a new developer does. Blank values there are set, not missing, so a default
    given to getenv never applies: this once made every call crash, in English too."""
    from pathlib import Path

    from dotenv import dotenv_values

    example = dotenv_values(Path(__file__).resolve().parents[1] / ".env.example")
    for name, value in example.items():
        monkeypatch.setenv(name, value or "")
    monkeypatch.setenv("SARVAM_API_KEY", "test")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test")
    monkeypatch.setenv("AGENT_LANGUAGE", language)

    assert agent_language() == language
    assert build_hearing(language, "phone").stt
    assert build_voice(language)
    assert voice_gender() in ("male", "female")
