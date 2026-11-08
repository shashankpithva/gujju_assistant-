"""Choosing the speech stack: no network, only that each choice builds and says what it can do."""

import pytest
from livekit.agents import stt
from livekit.plugins import deepgram, sarvam

from agent.languages import (
    FEMALE_VOICES,
    MALE_VOICES,
    FlushedSarvamSTT,
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
        "STT_PROVIDER", "SARVAM_STT_MODEL", "SARVAM_STT_MODE", "SARVAM_STT_FLUSH", "SARVAM_TTS_MODEL",
        "SARVAM_TTS_SPEAKER", "SARVAM_TTS_GENDER", "GU_TURN_DETECTOR",
    ):  # fmt: skip
        monkeypatch.delenv(name, raising=False)


def test_sarvam_hears_gujarati_in_codemix_mode_by_default():
    hearing = build_hearing("browser")
    assert type(hearing.stt) is sarvam.STT
    assert hearing.stt._opts.model == "saaras:v3"
    assert hearing.stt._opts.mode == "codemix"
    assert hearing.stt._opts.language.language == "gu"
    assert hearing.stt._opts.sample_rate == 16000


def test_phone_audio_is_declared_as_8_khz():
    assert build_hearing("phone").stt._opts.sample_rate == 8000


def test_an_stt_that_only_sends_finished_sentences_is_interrupted_by_any_speech():
    hearing = build_hearing("phone")
    assert hearing.partial_transcripts is False
    assert hearing.interruption == {"min_words": 0, "resume_false_interruption": True}


def test_flushing_asks_sarvam_for_the_words_as_soon_as_the_turn_ends(monkeypatch):
    monkeypatch.setenv("SARVAM_STT_FLUSH", "on")
    hearing = build_hearing("phone")
    assert isinstance(hearing.stt, FlushedSarvamSTT)
    assert hearing.stt.capabilities.manual_flush is True  # LiveKit flushes at the end of each turn
    assert hearing.stt._opts.flush_signal is True  # and the plugin passes it on to Sarvam
    assert build_hearing("phone").stt.capabilities.streaming


def test_sarvam_realtime_counts_words_and_has_a_backup(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "sarvam-realtime")
    hearing = build_hearing("phone")
    assert isinstance(hearing.stt, stt.FallbackAdapter)
    assert hearing.interruption["min_words"] == 2
    primary, backup = hearing.stt._stt_instances
    assert isinstance(primary, sarvam.STTRealtime) and isinstance(backup, sarvam.STT)


def test_deepgram_gujarati_is_an_alternative(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    hearing = build_hearing("phone")
    assert isinstance(hearing.stt, deepgram.STT) and hearing.partial_transcripts


def test_an_unknown_provider_is_refused(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "nope")
    with pytest.raises(ValueError, match="STT_PROVIDER"):
        build_hearing("phone")


def test_the_voice_is_sarvam_bulbul_in_gujarati():
    voice = build_voice()
    assert isinstance(voice, sarvam.TTS)
    assert voice._opts.target_language_code == "gu-IN" and voice._opts.speaker == "shubh"


def test_the_voice_gender_follows_the_speaker(monkeypatch):
    assert voice_gender() == "male"
    monkeypatch.setenv("SARVAM_TTS_SPEAKER", "pooja_gu_conversational")
    assert voice_gender() == "female"
    monkeypatch.setenv("SARVAM_TTS_SPEAKER", "someone_new")
    with pytest.raises(ValueError, match="SARVAM_TTS_GENDER"):
        voice_gender()
    monkeypatch.setenv("SARVAM_TTS_GENDER", "female")
    assert voice_gender() == "female"


def test_every_listed_voice_has_one_gender():
    assert not MALE_VOICES & FEMALE_VOICES


def test_turn_detection_can_be_switched_to_silence_alone(monkeypatch):
    assert build_turn_detection() != "vad"
    monkeypatch.setenv("GU_TURN_DETECTOR", "off")
    assert build_turn_detection() == "vad"


def test_the_voice_gets_gujarati_numbers():
    transforms = voice_text_transforms("male")
    assert transforms[:2] == ["filter_markdown", "filter_emoji"] and len(transforms) == 4
