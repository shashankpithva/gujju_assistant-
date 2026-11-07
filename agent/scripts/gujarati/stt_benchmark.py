"""Word error rate, names and phone numbers for each speech-to-text option.

    # Real recordings (the only numbers to trust): data/gujarati/recordings/<speaker>/<sentence id>.wav
    uv run python scripts/gujarati/stt_benchmark.py --providers saaras-v3,saaras-v4,deepgram-gu

    # No recordings yet: Sarvam's own voice reads the sentences. A smoke test, not a result.
    uv run python scripts/gujarati/stt_benchmark.py --synthetic --providers saaras-v3,deepgram-gu

Audio goes through the same 8 kHz mu-law as a phone line unless --no-phone is given, and is streamed
in real time through the agent's own STT, so the delay shown is the delay a call would have.
Synthetic runs say so in their output: a TTS voice is clean and has no accent, so WER on it says
little about real callers, and Sarvam hearing Sarvam's voice flatters Sarvam.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from audio import CACHE, ROOT, load_wav, phone_copy, save_wav, speech_context, synthesise
from check_providers import transcribe
from dotenv import load_dotenv

from agent.gujarati.speech import for_the_ear
from agent.languages import build_hearing, build_voice
from evals.gujarati_metrics import char_errors, digits_match, kept_words, word_errors

SENTENCES = ROOT / "evals/gujarati/stt_sentences.jsonl"
RECORDINGS = ROOT / "data/gujarati/recordings"
PROVIDERS = {
    "saaras-v3": {"STT_PROVIDER": "sarvam", "SARVAM_STT_MODEL": "saaras:v3", "SARVAM_STT_MODE": "codemix"},
    "saaras-v3-transcribe": {
        "STT_PROVIDER": "sarvam",
        "SARVAM_STT_MODEL": "saaras:v3",
        "SARVAM_STT_MODE": "transcribe",
    },
    "saaras-v4": {"STT_PROVIDER": "sarvam", "SARVAM_STT_MODEL": "saaras:v4", "SARVAM_STT_MODE": "codemix"},
    "saaras-realtime": {"STT_PROVIDER": "sarvam-realtime", "SARVAM_STT_MODE": "codemix"},
    "deepgram-gu": {"STT_PROVIDER": "deepgram", "GU_DEEPGRAM_LANGUAGE": "gu"},
    "deepgram-multi": {"STT_PROVIDER": "deepgram", "GU_DEEPGRAM_LANGUAGE": "multi"},
}


def load_sentences() -> dict[str, dict]:
    lines = SENTENCES.read_text(encoding="utf-8").splitlines()
    return {s["id"]: s for s in (json.loads(line) for line in lines if line.strip())}


def recordings(sentences: dict[str, dict]) -> list[tuple[str, dict, Path]]:
    found = []
    for path in sorted(RECORDINGS.glob("*/*.wav")):
        if path.stem in sentences:
            found.append((path.parent.name, sentences[path.stem], path))
    return found


async def synthetic_clips(sentences: dict[str, dict]) -> list[tuple[str, dict, Path]]:
    os.environ.setdefault("SARVAM_TTS_SPEAKER", "priya")
    voice = build_voice("gu")
    clips = []
    for sentence in sentences.values():
        path = CACHE / "stt_synthetic" / f"{sentence['id']}.wav"
        if not path.exists():
            audio, _ = await synthesise(voice, for_the_ear(sentence["text"]))
            save_wav(audio, path)
        clips.append(("synthetic-tts", sentence, path))
    return clips


def score(rows: list[dict]) -> str:
    errors, words = sum(r["word"][0] for r in rows), sum(r["word"][1] for r in rows)
    chars, length = sum(r["char"][0] for r in rows), sum(r["char"][1] for r in rows)
    kept, wanted = sum(r["kept"][0] for r in rows), sum(r["kept"][1] for r in rows)
    parts = [f"WER {100 * errors / max(words, 1):5.1f}%", f"CER {100 * chars / max(length, 1):5.1f}%"]
    if wanted:
        parts.append(f"key words {100 * kept / wanted:5.1f}%")
    digits = [r["digits"] for r in rows if r["digits"] is not None]
    if digits:
        parts.append(f"digits {sum(digits)}/{len(digits)}")
    return "  ".join(parts)


async def run(provider: str, clips: list[tuple[str, dict, Path]], phone: bool) -> list[dict]:
    os.environ.update(PROVIDERS[provider])
    hearing = build_hearing("gu", "phone" if phone else "browser")
    rows = []
    for speaker, sentence, path in clips:
        source = phone_copy(path, CACHE / "stt_phone" / speaker / path.name) if phone else path
        try:
            heard, delay = await transcribe(hearing.stt, load_wav(source))
        except Exception as e:
            print(f"  {provider} {sentence['id']}: FAILED {str(e)[:100]}")
            continue
        rows.append(
            {
                "provider": provider,
                "speaker": speaker,
                "id": sentence["id"],
                "group": sentence["group"],
                "said": sentence["text"],
                "heard": heard,
                "word": word_errors(sentence["text"], heard),
                "char": char_errors(sentence["text"], heard),
                "kept": kept_words(sentence.get("keep", []), heard),
                "digits": digits_match(sentence["digits"], heard) if "digits" in sentence else None,
                "delay_ms": round(delay * 1000),
            }
        )
    return rows


async def main() -> int:
    load_dotenv()
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--providers", default="saaras-v3", help=f"from: {', '.join(PROVIDERS)}")
    parser.add_argument("--synthetic", action="store_true", help="read by Sarvam's voice, not people")
    parser.add_argument("--no-phone", action="store_true", help="skip the 8 kHz mu-law step")
    args = parser.parse_args()
    sentences = load_sentences()
    async with speech_context():
        clips = await synthetic_clips(sentences) if args.synthetic else recordings(sentences)
        if not clips:
            print(f"No recordings in {RECORDINGS}. See docs/gujarati/README.md, or use --synthetic.")
            return 1
        speakers = len({speaker for speaker, _, _ in clips})
        print(f"{len(clips)} clips from {speakers} speaker(s)")
        if args.synthetic:
            print("SYNTHETIC SPEECH: a smoke test. These numbers say nothing about real callers.")
        results = []
        for provider in args.providers.split(","):
            rows = await run(provider, clips, not args.no_phone)
            results += rows
            if not rows:
                continue
            print(f"\n{provider}: {score(rows)}")
            print(f"  median delay after speech: {statistics.median(r['delay_ms'] for r in rows)} ms")
            groups = defaultdict(list)
            for row in rows:
                groups[row["group"]].append(row)
            for group, members in sorted(groups.items()):
                print(f"  {group:16} {score(members)}")
    out = CACHE / "stt_results.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    print(f"\nEvery transcript: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
