# Gujarati calls

The agent can take calls in natural Gujarati, including Gujarati mixed with English. English stays the default. For what was found and why it's built this way, see [audit.md](audit.md).

## Status

| Done, and tested without any API key | Still needs keys or people |
|---|---|
| Day, time, number, name and goodbye handling in Gujarati | Choosing a voice (nobody has listened to one) |
| Reply guard for false bookings, prices and codes, in Gujarati | Native-speaker review of the dataset |
| All fixed lines, the prompt, Sarvam and Deepgram wiring | Before-and-after audio |
| 554-conversation dataset, 119 eval scenarios, 59 STT sentences | STT word error rate on real speech |
| All measuring tools, tested against a stand-in API | LLM scores, and real voice latency |

**The dataset is synthetic.** Claude wrote every conversation, and every record says so. None has had native review, and the regional ones are approximations marked `_approx`. Don't describe them as anything else until people have reviewed them.

## Run it

All commands run from `agent/`.

```sh
cp .env.example .env     # add SARVAM_API_KEY, GROQ_API_KEY, GOOGLE_API_KEY, DEEPGRAM_API_KEY
uv sync
uv run python -m agent.main download-files
```

In `.env`, set `AGENT_LANGUAGE=gu`, then:

```sh
uv run python scripts/gujarati/check_providers.py    # what your account can use: run this first
uv run python -m agent.main console                  # talk to it in the terminal
lk agent dev src/agent/main.py                       # or join LiveKit Cloud, for a browser call
```

## From here to a real result

Each step feeds the next. Steps 1 to 3 need only keys. Steps 4 and 5 need people.

### 1. Check the account

`check_providers.py` tests each voice and STT option with one short request, and lists the LLMs your keys reach. It costs a few rupees of credit. Use what it shows to set `STT_PROVIDER` and `SARVAM_TTS_MODEL`.

### 2. Score the LLMs

```sh
uv run pytest evals/test_gujarati.py -q                                   # the configured chain
GROQ_MODELS=openai/gpt-oss-20b uv run pytest evals/test_gujarati.py -q    # another model
GROQ_MODELS=llama-3.3-70b-versatile uv run pytest evals/test_gujarati.py -q
LLM_PROVIDER=gemini uv run pytest evals/test_gujarati.py -q
uv run python scripts/gujarati/eval_report.py --latest                    # scores by metric and model
```

On PowerShell, set the variable first: `$env:GROQ_MODELS="openai/gpt-oss-20b"`.

One full run is roughly 300 LLM requests, which won't fit Groq's free daily budget in one go. Use `-k code_switch` to run a metric at a time, or a paid tier. `EVAL_PAUSE_SECONDS` (default 8) paces the runs. Results collect in `evals/results/`.

The scenarios measure comprehension, code-switching, names, numbers, relevance, consistency, safety, goodbyes and regional understanding. A judge model decides whether a reply did its job. It can't judge how natural a reply sounds, which is what step 4 is for.

### 3. Make the audio

```sh
uv run python scripts/gujarati/voice_audition.py                      # 12 voices, about 25 rupees
uv run python scripts/gujarati/voice_audition.py --voices shubh,bhavik_gu_conversation --paces 0.9,1.0,1.1
```

This writes `.cache/gujarati/audition/`, which holds the before-and-after clips and a rating page. Every clip is the 8 kHz mu-law copy, because that's what a caller hears: judging a voice from studio audio tells you little about a phone call.

"Before" here is word-for-word Gujarati in the same voice, so listeners compare the writing, not the voice. There's no English-stack "before", since Aura can't speak Gujarati.

### 4. Get native speakers to listen

Zip `.cache/gujarati/audition/` and send it to at least five people whose first language is Gujarati, ideally from different parts of Gujarat and of different ages. They open `index.html`, rate each clip, and download a ratings file. Clips are shuffled and numbered, so nobody knows what they're hearing. Tell them these are AI voices.

```sh
uv run python scripts/gujarati/score_ratings.py path/to/ratings-*.json
```

It ranks the voices, shows before and after, and lists every note. It counts native speakers only, and says so when there are too few to rely on.

Then close the loop:

| They report | Fix it in |
|---|---|
| A mispronounced word | `LEXICON` in [gujarati/speech.py](../../src/agent/gujarati/speech.py), or a Sarvam pronunciation dictionary (`SARVAM_TTS_DICT_ID`) |
| Too fast or too slow | `SARVAM_TTS_PACE` |
| Flat, or over-acted | `SARVAM_TTS_TEMPERATURE` (`bulbul:v3` only) |
| A stiff fixed line | [gujarati/lines.py](../../src/agent/gujarati/lines.py) |
| Stiff LLM wording | [prompts/receptionist_gu.md](../../src/agent/prompts/receptionist_gu.md), and a new rule in [gujarati/style.py](../../src/agent/gujarati/style.py) |
| A wrong number word | `_WORDS` or `VARIANTS` in [gujarati/numbers.py](../../src/agent/gujarati/numbers.py). Spellings there need a native check anyway |

Rerun the audition and rate again.

**Dataset review** works the same way, as a spreadsheet:

```sh
uv run python scripts/gujarati/review_sheet.py export review.csv
uv run python scripts/gujarati/review_sheet.py export regional.csv --category regional
uv run python scripts/gujarati/review_sheet.py import review.csv --reviewer "Name, Rajkot"
uv run python scripts/gujarati/build_dataset.py
```

Reviewers mark each conversation `ok`, `fix` or `reject`. Send `regional` conversations to someone from that region: those are the least reliable. Only a named person's verdict changes a record from `pending`.

### 5. Measure hearing on real voices

Have at least five people, across ages, regions and genders, read [evals/gujarati/stt_sentences.jsonl](../../evals/gujarati/stt_sentences.jsonl). Get their consent first, and tell them what the recordings are for. Save one 16-bit mono WAV per sentence, named by its id:

```
data/gujarati/recordings/<speaker>/mix-01.wav
```

That folder is ignored by git: **never commit people's voices.** Real phone recordings are better still.

```sh
uv run python scripts/gujarati/stt_benchmark.py --providers saaras-v3,saaras-v4,saaras-realtime,deepgram-gu,deepgram-multi
```

This gives WER, CER, key-word accuracy (names, places, code-mixed words), phone-number accuracy and delay, for each provider and each sentence group. `--synthetic` works with no recordings but only proves the tool runs: a TTS voice is clean and accentless, and Sarvam hearing Sarvam flatters Sarvam.

### 6. Measure real latency

Run the agent with `uv run python -m agent.main dev`, then:

```sh
uv run python scripts/voice_benchmark.py --language gu
```

The agent's log shows where the time went, turn by turn. Compare `SARVAM_TTS_CODEC=linear16`, `GU_TURN_DETECTOR=off` and each STT provider.

## Targets

These are proposals. Adjust them once you have a baseline.

| Metric | Measured with | Proposed target |
|---|---|---|
| Native-speaker naturalness | `score_ratings.py`, at least 5 raters, phone audio | Mean of 4.0 out of 5 or better |
| Pronunciation accuracy | Same | Mean of 4.2 out of 5 or better |
| Gujarati comprehension, relevance, consistency | `eval_report.py` | 90% or better |
| Code-switching | Same | 90% or better |
| Safety and goodbyes | Same | 100% |
| STT word error rate | `stt_benchmark.py` | Baseline first, then pick the best provider |
| Name recognition | Key words, `names` group | 90% or better, with read-back catching the rest |
| Phone number accuracy | `digits` | 95% or better |
| Voice-to-voice latency | `voice_benchmark.py` and the agent log | p50 under 800 ms is the repo's target. Gujarati adds 0.2 s of deliberate waiting, so expect to spend time here |

## Environment variables

Only `AGENT_LANGUAGE` and `SARVAM_API_KEY` are required for Gujarati. [.env.example](../../.env.example) explains each one in place.

| Variable | Default | What it does |
|---|---|---|
| `AGENT_LANGUAGE` | `en` | `en` or `gu`, for calls. Chats stay English |
| `SARVAM_API_KEY` | | From dashboard.sarvam.ai |
| `STT_PROVIDER` | by language | `deepgram`, `sarvam` or `sarvam-realtime` |
| `SARVAM_STT_MODEL` | `saaras:v3` | Or `saaras:v4`. Ignored by `sarvam-realtime` |
| `SARVAM_STT_MODE` | `codemix` | Or `transcribe`, `verbatim`, `translit` |
| `SARVAM_STT_STREAM_TYPE` | `balanced` | `fast`, `balanced` or `simulated`, for `sarvam-realtime` |
| `SARVAM_STT_PHONE_SAMPLE_RATE` | `8000` | For phone calls. Browser calls use 16000 |
| `GU_DEEPGRAM_LANGUAGE` | `gu` | `gu` or `multi`, when `STT_PROVIDER=deepgram` |
| `TTS_PROVIDER` | by language | Gujarati needs `sarvam` |
| `SARVAM_TTS_MODEL` | `bulbul:v3` | Or `bulbul:v4-flash` |
| `SARVAM_TTS_SPEAKER` | `shubh` | Provisional. The grammar follows this voice |
| `SARVAM_TTS_GENDER` | from the voice | Only for a voice not in `languages.py` |
| `SARVAM_TTS_PACE` | `1.0` | Speaking speed |
| `SARVAM_TTS_TEMPERATURE` | `0.6` | Expressiveness, on `bulbul:v3` |
| `SARVAM_TTS_SAMPLE_RATE` | `24000` | Streaming tops out at 24 kHz |
| `SARVAM_TTS_CODEC` | `mp3` | `linear16` may start sooner: measure it |
| `SARVAM_TTS_DICT_ID` | | A Sarvam pronunciation dictionary |
| `GU_TURN_DETECTOR` | `on` | `off` uses silence alone, for comparison |

**On LiveKit Cloud:** add these to `.env.production`, then run `lk agent update-secrets --secrets-file .env.production --overwrite`.

## Per-restaurant Gujarati

No code is needed for these, and neither needs a contract change.

- **Greeting:** put a Gujarati greeting in `restaurants.greeting`, and the agent uses it as written. It still adds the AI, staff and recording lines after it.
- **Info answers:** add `info_entries` rows with `language = 'gu'`. Anything without one falls back to English, and the LLM puts it into Gujarati.

## Checks

```sh
uv run ruff format . && uv run ruff check . && uv run pytest -q     # no keys needed, as in CI
uv run python scripts/gujarati/build_dataset.py --check
```

After changing anything in `data/gujarati/source/`, run `build_dataset.py` without `--check`. The source format is explained at the top of that script. The build fails on a style-rule breach, on a duplicate, or when one opening sentence starts more than 4% of agent lines.
