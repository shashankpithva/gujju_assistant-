"""The Gujarati scripts, run for real against a stand-in for Sarvam's API.

The plugin, the request it sends, the audio decoding, ffmpeg and the scoring are all the real thing.
Only the far end of the connection is fake: nothing here says a real voice sounds good, or that a
real account has access to a model. check_providers.py finds that out.
"""

import asyncio
import base64
import importlib.util
import io
import json
import math
import shutil
import struct
import sys
import wave
from pathlib import Path

import pytest
from aiohttp import web
from livekit.agents import stt

from agent.languages import build_voice

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts/gujarati"
sys.path.insert(0, str(SCRIPTS))


def script(name: str):
    spec = importlib.util.spec_from_file_location(f"gu_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it's still loading
    spec.loader.exec_module(module)
    return module


def tone_wav(seconds: float = 0.4, rate: int = 24000) -> bytes:
    samples = [int(9000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(int(seconds * rate))]
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return out.getvalue()


@pytest.fixture
async def fake_sarvam(monkeypatch):
    """Sarvam's text-to-speech endpoint on localhost: records each request, answers with a tone."""
    requests = []

    async def text_to_speech(request):
        requests.append({"key": request.headers.get("api-subscription-key"), **await request.json()})
        return web.json_response({"audios": [base64.b64encode(tone_wav()).decode()], "request_id": "t"})

    app = web.Application()
    app.router.add_post("/text-to-speech", text_to_speech)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    monkeypatch.setenv("SARVAM_TTS_CODEC", "wav")
    import agent.languages as languages

    real_tts = languages.sarvam.TTS

    def local_tts(**options):
        return real_tts(base_url=f"http://127.0.0.1:{port}/text-to-speech", **options)

    monkeypatch.setattr(languages.sarvam, "TTS", local_tts)
    yield requests
    await runner.cleanup()


async def test_gujarati_text_reaches_the_api_as_configured(fake_sarvam, monkeypatch):
    audio = script("audio")
    monkeypatch.setenv("SARVAM_TTS_SPEAKER", "priya")
    async with audio.speech_context():
        said, first = await audio.synthesise(build_voice("gu"), "કાલે સાંજે સાડા સાત વાગ્યે આવજો.")
    sent = fake_sarvam[0]
    assert sent["key"] == "test-key"
    assert sent["target_language_code"] == "gu-IN"
    assert sent["model"] == "bulbul:v3" and sent["speaker"] == "priya"
    assert "સાડા સાત" in (sent.get("inputs") or [sent.get("text")])[0]
    assert said.seconds == pytest.approx(0.4, abs=0.05)
    assert first > 0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_the_phone_copy_really_is_narrowband(tmp_path):
    audio = script("audio")
    source = tmp_path / "studio.wav"
    source.write_bytes(tone_wav())
    copy = audio.phone_copy(source, tmp_path / "phone.wav")
    loaded = audio.load_wav(copy)
    assert loaded.sample_rate == 8000
    assert loaded.seconds == pytest.approx(0.4, abs=0.05)
    assert not (tmp_path / "phone.mulaw.wav").exists()


def test_every_audition_voice_is_accepted_by_the_plugin(monkeypatch):
    audition = script("voice_audition")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    for model, voices in audition.VOICES.items():
        for voice in voices:
            monkeypatch.setenv("SARVAM_TTS_MODEL", model)
            monkeypatch.setenv("SARVAM_TTS_SPEAKER", voice)
            assert build_voice("gu")._opts.speaker == voice
            assert audition.model_of(voice) == model


def test_before_and_after_really_differ_by_the_style_rules():
    from agent.gujarati.style import check_line

    audition = script("voice_audition")
    assert audition.SENTENCES and len(audition.BEFORE_AFTER) >= 5
    for moment, (before, after) in audition.BEFORE_AFTER.items():
        assert check_line(before), moment  # each "before" shows a real problem
        assert not check_line(after), moment


def test_rating_page_and_scores_work_end_to_end(tmp_path, capsys, monkeypatch):
    audition = script("voice_audition")
    scoring = script("score_ratings")

    def voice_clip(voice: str, file: str) -> dict:
        return {
            "clip": f"{voice}-1.0-time",
            "file": file,
            "text": "સાડા સાત",
            "kind": "voice",
            "voice": voice,
            "pace": 1.0,
        }

    clips = [
        voice_clip("shubh", "a.wav"),
        voice_clip("priya", "b.wav"),
        {"clip": "compare-x-before", "file": "c.wav", "text": "x", "kind": "before", "moment": "x"},
        {"clip": "compare-x-after", "file": "d.wav", "text": "y", "kind": "after", "moment": "x"},
    ]
    page = tmp_path / "index.html"
    audition.build_page(clips, page)
    html = page.read_text(encoding="utf-8")
    assert html.count('class="clip"') == 4 and "ratings-" in html

    clips_file = tmp_path / "clips.json"
    clips_file.write_text(json.dumps(clips, ensure_ascii=False), encoding="utf-8")
    files = []
    for i, (shubh, priya, before, after) in enumerate([(4, 3, 2, 4), (5, 3, 2, 5), (4, 2, 1, 4)]):
        ratings = [
            {"clip": "shubh-1.0-time", "natural": shubh, "pronunciation": 4, "note": ""},
            {"clip": "priya-1.0-time", "natural": priya, "pronunciation": 3, "note": "સાડા ખોટું"},
            {"clip": "compare-x-before", "natural": before, "pronunciation": 3, "note": ""},
            {"clip": "compare-x-after", "natural": after, "pronunciation": 5, "note": ""},
        ]
        path = tmp_path / f"r{i}.json"
        path.write_text(json.dumps({"rater": f"r{i}", "native": True, "ratings": ratings}), encoding="utf-8")
        files.append(str(path))
    outsider = tmp_path / "learner.json"
    outsider.write_text(json.dumps({"rater": "learner", "native": False, "ratings": []}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", *files, str(outsider), "--clips", str(clips_file)])
    assert scoring.main() == 0
    out = capsys.readouterr().out
    assert "3 native speakers counted; left out: learner" in out
    assert "first impression, not a result" in out  # 3 is under MIN_RATERS
    assert out.index("shubh") < out.index("priya")  # best first
    assert "+2.67" in out
    assert "સાડા ખોટું" in out


def test_review_sheet_round_trip_records_who_reviewed(tmp_path, monkeypatch):
    sheet = script("review_sheet")
    monkeypatch.setattr(sheet, "REVIEWS", tmp_path / "reviews.jsonl")
    csv_file = tmp_path / "review.csv"
    assert sheet.export(csv_file, "regional") == 0
    text = csv_file.read_text(encoding="utf-8-sig")
    assert "kathiawadi_approx" in text and "ફોન કરનાર:" in text
    first_id = text.splitlines()[1].split(",")[0]

    lines = csv_file.read_text(encoding="utf-8-sig").replace(
        f"{first_id},regional", f"{first_id},regional", 1
    )
    import csv as csv_module

    rows = list(csv_module.DictReader(io.StringIO(lines)))
    rows[0]["verdict"] = "ok"
    with csv_file.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv_module.DictWriter(out, fieldnames=sheet.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    assert sheet.import_verdicts(csv_file, "A reviewer, Rajkot") == 0
    saved = [
        json.loads(line) for line in (tmp_path / "reviews.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert saved == [{"id": first_id, "verdict": "ok", "suggestion": "", "reviewer": "A reviewer, Rajkot"}]


class FakeStream:
    """An STT stream: answers once it has heard enough audio, like a server finishing a sentence."""

    def __init__(self, text: str, after_frames: int) -> None:
        self.text, self.after, self.frames = text, after_frames, 0
        self._queue: asyncio.Queue = asyncio.Queue()

    def push_frame(self, _frame) -> None:
        self.frames += 1
        if self.frames == self.after:
            event = stt.SpeechEvent(
                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[stt.SpeechData(language="gu", text=self.text)],
            )
            self._queue.put_nowait(event)

    def end_input(self) -> None:
        self._queue.put_nowait(None)

    async def aclose(self) -> None:
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        event = await self._queue.get()
        if event is None:
            raise StopAsyncIteration
        return event


async def test_transcribe_returns_the_words_and_the_delay_after_speech():
    providers = script("check_providers")
    audio = script("audio")

    class Fake:
        def stream(self):
            return FakeStream("નમસ્તે", after_frames=15)

    clip = audio.Audio(bytes(2 * 16000 // 5), 16000)  # 0.2 s: 10 frames of speech
    text, delay = await providers.transcribe(Fake(), clip)
    assert text == "નમસ્તે"
    assert 0 < delay < 2


def test_stt_scores_add_up():
    bench = script("stt_benchmark")
    row = {"word": (1, 10), "char": (2, 50), "kept": (3, 4), "digits": True}
    line = bench.score([row, {**row, "digits": False}])
    assert "WER  10.0%" in line and "CER   4.0%" in line and "key words  75.0%" in line
    assert "digits 1/2" in line


def test_every_stt_option_builds(monkeypatch):
    from agent.languages import build_hearing

    bench = script("stt_benchmark")
    monkeypatch.setenv("SARVAM_API_KEY", "test")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test")
    for env in bench.PROVIDERS.values():
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        assert build_hearing("gu", "phone").stt


def test_every_stt_sentence_with_digits_is_a_real_number():
    bench = script("stt_benchmark")
    for sentence in bench.load_sentences().values():
        if "digits" in sentence:
            assert sentence["digits"].replace(" ", "").isdigit(), sentence["id"]
