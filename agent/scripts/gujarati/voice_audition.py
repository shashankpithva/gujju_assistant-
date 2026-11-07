"""Generate the audio native speakers will judge: the voices side by side, and before against after.

    uv run python scripts/gujarati/voice_audition.py                  # every candidate voice
    uv run python scripts/gujarati/voice_audition.py --voices bhavik_gu_conversation,shubh --pace 0.95,1.0
    uv run python scripts/gujarati/voice_audition.py --paces 0.9,1.0,1.1 --voices shubh

Writes to .cache/gujarati/audition/ and prints the path of index.html. Open it, or zip the folder and
send it to native speakers. Clips are shuffled and named by number, so nobody knows which voice or
version they're hearing. Each person downloads their ratings as a file, for score_ratings.py.

Every clip is the phone-quality copy: 8 kHz mu-law, what a caller really hears.

Cost: about 3 rupees per 1,000 characters on bulbul:v3 and 1 on bulbul:v4-flash. The default run is
roughly 12 voices x 1,000 characters, about 25 rupees of the 100 rupees of free credit.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import random
import sys
from pathlib import Path

from audio import CACHE, phone_copy, save_wav, speech_context, synthesise
from dotenv import load_dotenv

from agent.gujarati.speech import for_the_ear
from agent.languages import FEMALE_VOICES, build_voice

OUT = CACHE / "audition"

# Each tests something a listener can judge: intonation, numbers, names, English inside Gujarati.
SENTENCES = {
    "greeting": "નમસ્તે, The Saffron Table માંથી બોલું છું. હું AI આસિસ્ટન્ટ છું, અને સ્ટાફ માટે મેસેજ પણ લઈ શકું છું.",
    "question": "કાલે રાત્રે કેટલા લોકો માટે ટેબલ જોઈએ છે?",
    "time": "સરસ, મંગળવારે સાંજે સાડા સાત વાગ્યે ચાર જણ માટે ટેબલ મળી જશે.",
    "alternatives": "માફ કરજો, સાડા સાત વાગ્યે જગ્યા નથી. રાત્રે આઠ, સવા આઠ કે પોણા નવ વાગ્યે ફાવશે?",
    "phone": "તમારો નંબર નવ આઠ બે પાંચ શૂન્ય, એક બે ત્રણ ચાર પાંચ છે, બરાબર?",
    "code": "થઈ ગયું! તમારો બુકિંગ કોડ છે: કે, સાત, ક્યૂ, બે.",
    "names": "ધર્મેન્દ્રસિંહ જાડેજા, જિજ્ઞા ત્રિવેદી અને ફાલ્ગુની દવેના નામે ટેબલ રાખ્યું છે.",
    "places": "અમદાવાદ, વડોદરા, સુરત, રાજકોટ, ભાવનગર અને જામનગરથી મહેમાન આવે છે.",
    "price": "પનીર ટિક્કા 380 રૂપિયાનું છે, અને દાલ મખની 380 રૂપિયાની.",
    "code_mix": "હા, બિલકુલ. તમારું બુકિંગ કન્ફર્મ કરીને WhatsApp નહીં, ફોન પર જ કોડ કહી દઉં.",
    "apology": "અરે, માફ કરજો, તકલીફ પડી. મેનેજરને કહી દઉં, એ સામેથી ફોન કરશે.",
    "warm": "વાહ, જન્મદિવસની શુભેચ્છા! સરસ, કોઈ વાંધો નહીં, બધું થઈ જશે.",
}

# The same moment before and after. "Before" is what word-for-word translation gives; "after" is how
# the agent says it now. Both use the same voice, so listeners judge the writing, not the voice.
BEFORE_AFTER = {
    "opening": (
        "નમસ્કાર. હું તમને માહિતી એકત્રિત કરવા માટે સંપર્ક કરી રહ્યો છું.",
        "નમસ્તે, કેમ છો? તમારી સાથે થોડી માહિતી અંગે વાત કરવી હતી. અત્યારે વાત કરવાનો સમય છે?",
    ),
    "booking": (
        "કૃપા કરીને આપનું નામ જણાવો જેથી આરક્ષણ કરવામાં આવી શકે.",
        "કયા નામે બુક કરું?",
    ),
    "availability": (
        "7:30 PM પર ટેબલ ઉપલબ્ધ નથી. 8:00 PM ઉપલબ્ધ છે.",
        "માફ કરજો, સાંજે સાડા સાત વાગ્યે જગ્યા નથી. રાત્રે આઠ વાગ્યે ફાવશે?",
    ),
    "price": (
        "પનીર ટિક્કાની કિંમત રૂ. 380 છે.",
        "પનીર ટિક્કા ત્રણસો એંસી રૂપિયાનું છે.",
    ),
    "goodbye": (
        "આપનો કૉલ કરવા બદલ આભાર. આપનો દિવસ શુભ રહે.",
        "ફોન કરવા બદલ આભાર. મંગળવારે મળીએ, આવજો!",
    ),
}

# Candidates: v3's customer-care voices plus the Gujarati personas of bulbul:v4-flash. Which is best
# is exactly what this script is for; nothing here has been listened to yet.
VOICES = {
    "bulbul:v3": ("shubh", "manan", "rahul", "amit", "ratan", "ritu", "priya", "pooja", "kavya"),
    "bulbul:v4-flash": ("bhavik_gu_conversation", "pooja_gu_conversational", "pooja_gu_customer"),
}
BEFORE_AFTER_VOICE = ("bulbul:v3", "shubh")


def model_of(voice: str) -> str:
    return "bulbul:v4-flash" if voice in VOICES["bulbul:v4-flash"] else "bulbul:v3"


async def render(voice_name: str, model: str, pace: float, text: str, name: str, ear: bool = True) -> tuple:
    os.environ.update(
        {"SARVAM_TTS_MODEL": model, "SARVAM_TTS_SPEAKER": voice_name, "SARVAM_TTS_PACE": str(pace)}
    )
    gender = "female" if voice_name in FEMALE_VOICES else "male"
    spoken = for_the_ear(text, gender) if ear else text
    audio, first = await synthesise(build_voice("gu"), spoken)
    studio = OUT / "studio" / f"{name}.wav"
    save_wav(audio, studio)
    return phone_copy(studio, OUT / "clips" / f"{name}.wav"), first


def _score(name: str) -> str:
    options = "".join(f"<option>{n}</option>" for n in ("", 1, 2, 3, 4, 5))
    return f'<select name="{name}">{options}</select>'


def build_page(clips: list[dict], path: Path) -> None:
    """A self-contained rating page. Clips are referred to by a number, never by voice."""
    rows = "\n".join(
        f"""<section class="clip" data-clip="{html.escape(c["clip"])}">
  <p class="n">{i}</p>
  <audio controls preload="none" src="clips/{html.escape(c["file"])}"></audio>
  <p class="text">{html.escape(c["text"])}</p>
  <label>કેટલું કુદરતી લાગે છે? <span class="hint">1 મશીન, 5 માણસ જેવું</span>
    {_score("natural")}</label>
  <label>ઉચ્ચાર સાચા છે? <span class="hint">1 ખોટા, 5 બરાબર</span>
    {_score("pronunciation")}</label>
  <label>ખોટો ઉચ્ચાર કે નોંધ <input name="note"></label>
</section>"""
        for i, c in enumerate(clips, 1)
    )
    path.write_text(
        f"""<!doctype html><html lang="gu"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>અવાજ મૂલ્યાંકન</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:640px;margin:0 auto;padding:16px;color:#222}}
.clip{{border-top:1px solid #ddd;padding:12px 0}}.n{{color:#888;margin:0}}audio{{width:100%}}
label{{display:block;margin:6px 0}}.hint{{color:#777;font-size:13px}}input{{width:100%}}
.who label{{margin-bottom:10px}}button{{font:inherit;padding:10px 16px;margin:16px 0}}</style></head><body>
<h1>અવાજ મૂલ્યાંકન</h1>
<p>દરેક અવાજ સાંભળો, જાણે કોઈએ ફોન કર્યો હોય. આ AI અવાજો છે. સાચા જવાબ જેવું કંઈ નથી, તમને જે લાગે તે કહો.</p>
<div class="who"><label>તમારું નામ <input id="who"></label>
<label>તમે ક્યાંના છો? (ગામ / શહેર) <input id="from"></label>
<label>ગુજરાતી તમારી માતૃભાષા છે?
<select id="native"><option></option><option>હા</option><option>ના</option></select></label></div>
{rows}
<button id="save">મારા જવાબ સાચવો</button>
<script>
document.getElementById('save').onclick = () => {{
  const ratings = [...document.querySelectorAll('.clip')].map(c => ({{
    clip: c.dataset.clip,
    natural: Number(c.querySelector('[name=natural]').value) || null,
    pronunciation: Number(c.querySelector('[name=pronunciation]').value) || null,
    note: c.querySelector('[name=note]').value,
  }}));
  const data = {{rater: document.getElementById('who').value, from: document.getElementById('from').value,
    native: document.getElementById('native').value === 'હા', ratings}};
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], {{type: 'application/json'}}));
  link.download = 'ratings-' + (data.rater || 'rater').replace(/\\s+/g, '-') + '.json';
  link.click();
}};
</script></body></html>""",
        encoding="utf-8",
    )


async def main() -> int:
    load_dotenv()
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--voices", help="comma-separated; default: every candidate")
    parser.add_argument("--paces", default="1.0", help="comma-separated, e.g. 0.9,1.0,1.1")
    parser.add_argument("--sentences", help="comma-separated names from SENTENCES; default: all")
    parser.add_argument("--seed", type=int, default=7, help="the shuffle, so a rerun gives the same order")
    args = parser.parse_args()
    if not os.getenv("SARVAM_API_KEY"):
        print("SARVAM_API_KEY isn't set in agent/.env.")
        return 1
    voices = args.voices.split(",") if args.voices else [v for group in VOICES.values() for v in group]
    paces = [float(p) for p in args.paces.split(",")]
    names = args.sentences.split(",") if args.sentences else list(SENTENCES)
    clips: list[dict] = []
    async with speech_context():
        for voice in voices:
            for pace in paces:
                for sentence in names:
                    name = f"{voice}-{pace}-{sentence}"
                    try:
                        _, first = await render(voice, model_of(voice), pace, SENTENCES[sentence], name)
                    except Exception as e:
                        print(f"FAILED {name}: {str(e)[:120]}")
                        continue
                    clips.append(
                        {
                            "clip": name,
                            "file": f"{name}.wav",
                            "text": SENTENCES[sentence],
                            "kind": "voice",
                            "voice": voice,
                            "pace": pace,
                            "sentence": sentence,
                            "first_audio_ms": round(first * 1000),
                        }
                    )
                    print(f"{name}: first audio {first * 1000:.0f} ms")
        model, voice = BEFORE_AFTER_VOICE
        for moment, (before, after) in BEFORE_AFTER.items():
            # "Before" goes in as written, as nothing rewrote text for the voice before this work.
            for version, text, ear in (("before", before, False), ("after", after, True)):
                name = f"compare-{moment}-{version}"
                await render(voice, model, 1.0, text, name, ear=ear)
                clips.append(
                    {"clip": name, "file": f"{name}.wav", "text": text, "kind": version, "moment": moment}
                )
    random.Random(args.seed).shuffle(clips)
    build_page(clips, OUT / "index.html")
    (OUT / "clips.json").write_text(json.dumps(clips, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(clips)} clips. Rating page: {OUT / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
