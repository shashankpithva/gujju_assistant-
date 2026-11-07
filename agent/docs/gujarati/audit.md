# Gujarati voice: pipeline audit, recommendations, fine-tuning assessment

Written 7 Nov 2026, against `livekit-agents` 1.8.9 and `livekit-plugins-sarvam` 1.8.9. Facts about the code were checked by running it or reading its source. Provider facts come from the official docs on that date (links at the end). **No live API or real audio was used**: no Sarvam, Groq or Gemini key was available when this was written, so anything about sound or accuracy is still to be measured. [README.md](README.md) says how.

## 1. What the audit found

**Swapping the STT and TTS alone would have shipped a broken, less safe agent.** English was built into the deterministic layers around the models, and those failures make no noise: nothing crashes, the agent just misbehaves. Each row below was reproduced against the original code.

| Layer | Original behaviour on Gujarati | Consequence |
|---|---|---|
| [guard.py](../../src/agent/guard.py), booking claims | "તમારું ટેબલ બુક થઈ ગયું" isn't recognised as a claim | A false "you're booked" reaches the caller, who arrives with no table |
| guard.py, prices | "999 રૂપિયા" isn't recognised as a price | An invented price reaches the caller |
| guard.py, sentences | Sentence end requires a capital letter after it, and Gujarati has none | The whole reply is held until the LLM finishes, so the voice can't start early |
| [tools.py](../../src/agent/tools.py), `resolve_day` | Strips everything outside `a-z`, so "મંગળવારે" becomes nothing | No Gujarati day can be booked |
| tools.py, `caller_is_done` | "આવજો" isn't a goodbye | `end_call` refuses, and the line stays open until the silence timer |
| [speakable.py](../../src/agent/speakable.py), `normalize_phone` | `\d` matches Gujarati digits, giving `+91૯૮૭૬૫૪૩૨૧૦` | An invalid number, which the API rejects |
| speakable.py, `spoken_digits` | "નવ આઠ સાત" gives an empty string | A spoken phone number never registers |
| [turn_taking.py](../../src/agent/turn_taking.py) | "ફોન નંબર" doesn't match, so the quick 0.3 s floor stays on | Callers are cut off mid-number |
| tools.py, every fixed line | About 40 English lines go straight to the voice | English in a Gujarati voice, at the most important moments |
| tools.py, `take_message` | The API's English `summary` is spoken as it stands | The same, and it needs no web change to fix |
| [main.py](../../src/agent/main.py) | `stt.update_options(keyterm=...)` is Deepgram-only | Would raise on Sarvam, in a background task, and kill the fact loading |
| [call_log.py](../../src/agent/call_log.py) | `language="en"` is hard-coded | Dashboard analytics would be wrong |

Python regular expressions add a trap of their own: `\b` and `\w` treat Gujarati vowel signs and the virama as non-word characters. `\bહા\b` doesn't match "હા, બરાબર", and `\bના\b` matches inside "નાસ્તો". The new code splits text into words instead.

Reading the plugin and LiveKit source also turned up four things the docs don't say:

1. **`sarvam.STT` declares `interim_results=True` but only ever sends finals.** The repo's `min_words: 2` counts words in transcripts, so barge-in couldn't fire until the caller finished a whole sentence. With this STT, any speech now stops the agent, and `resume_false_interruption` recovers from a cough. `sarvam.STTRealtime` does send partials and keeps the two-word rule.
2. **LiveKit's turn detector still runs on Gujarati.** Gujarati isn't among its 14 languages, but `supports()` returns true whenever a default threshold exists, so it runs on English's calibration rather than being skipped. Gujarati now uses Hindi's threshold. That is an assumption to test, with raised floors as protection. The detector can only lengthen a wait, never shorten it.
3. **`STTRealtime` never reconnects** (`max_retry` is forced to 0, as the endpoint bills per connection). One dropped socket would leave the agent deaf, so it runs behind a `FallbackAdapter` onto the websocket STT.
4. **`bulbul:v4-flash` has Gujarati voices of its own** (`bhavik_gu_conversation`, `pooja_gu_conversational`, `pooja_gu_customer`). They appear in the plugin's model list.

### What needed no change

`web/` and `contracts/` stay untouched. `calls.language` is free text, the `info` route already looks up per-language wording with an English fallback (`load_facts` now asks for it), and `restaurants.greeting` can hold a Gujarati greeting, which the agent then uses as written.

## 2. What was built

| Part | Where | What it does |
|---|---|---|
| Language layer | [gujarati/numbers.py](../../src/agent/gujarati/numbers.py) | Number words, સાડા/સવા/પોણા/દોઢ/અઢી times, dates, phone digits, booking codes, both directions |
| Understanding | [gujarati/understanding.py](../../src/agent/gujarati/understanding.py) | Days (કાલે, પરમ દિવસે, 27મી) and goodbyes (આવજો, ફોન મૂકું છું). A greeting never hangs up, however similar |
| Fixed lines | [gujarati/lines.py](../../src/agent/gujarati/lines.py) | Every line the tools speak, written as Gujarati rather than translated |
| Voice text | [gujarati/speech.py](../../src/agent/gujarati/speech.py) | "7:30 PM" becomes "સાંજે સાડા સાત વાગ્યે", plus prices, phone digits, brand names, and verbs matched to the voice's gender |
| Style rules | [gujarati/style.py](../../src/agent/gujarati/style.py) | Catches bookish words, તું, passives and repeated openers, in the dataset build and the evals |
| Providers | [languages.py](../../src/agent/languages.py) | Every STT, TTS and turn-detection choice is an environment variable |
| Prompt | [prompts/receptionist_gu.md](../../src/agent/prompts/receptionist_gu.md) | Gujarati-first style and examples, with the English prompt's safety rules intact |

`AGENT_LANGUAGE` defaults to `en`, and every English line, regex path and test is unchanged.

**Gender is a Gujarati-specific trap worth knowing about.** First-person verbs change with the speaker ("સમજી ગયો" / "સમજી ગઈ"), so a woman's voice saying "સમજી ગયો" sounds wrong to any native ear. The grammar now follows the voice: the prompt says which, fixed lines avoid gendered verbs altogether, and the voice text corrects any slip.

## 3. Recommended configuration

Nothing here has been heard or measured yet, so these are the starting points to test, not results.

| Layer | Start with | Why | To settle it |
|---|---|---|---|
| STT | `STT_PROVIDER=sarvam`, `saaras:v3`, `codemix` | Works on any account, and keeps English words in English: "હું office માં છું" | `stt_benchmark.py` on real recordings |
| STT upgrade | `STT_PROVIDER=sarvam-realtime` | Restores word-counted barge-in and adds term biasing. Needs a subscription with realtime access | `check_providers.py` shows if you have it |
| STT alternative | `STT_PROVIDER=deepgram` (Nova-3 `gu`) | Gujarati since May 2026, improved in August. Has partials and keyterms, on the $200 credit | Same benchmark. A genuine contender |
| TTS | `bulbul:v3`, `shubh` | As requested, and the plugin's default voice. Male, to match the "સમજી ગયો" in the brief | `voice_audition.py` with native listeners |
| TTS candidate | `bulbul:v4-flash`, `bhavik_gu_conversation` | A Gujarati voice by name, at a third of the price. Sarvam recommends v4 Flash for new work | Same audition. **Try this one first** |
| LLM | The existing chain, unchanged | Its tool-calling is proven here. Language alone doesn't justify moving | Run the evals per model (below) |
| Turn-taking | Detector on with Hindi's threshold, floors 0.5 / 0.8 / 1.2 s | Protects callers who pause, for about 0.2 s per reply | Compare `GU_TURN_DETECTOR=off` on real calls |

### LLM candidates

Changing the LLM won't improve the voice: it affects wording and tool use only. Candidates on Groq's production list are `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`; Gemini's are `gemini-3.5-flash-lite` and `gemini-3.8-flash`. Public benchmarks don't settle this: IndicGenBench and MILU cover older models, and I found no Gujarati results for gpt-oss. The 119 scenarios exist to answer it for this exact job.

What was measured is cost, with gpt-oss's tokenizer (`o200k_harmony`):

| | English | Gujarati | |
|---|---|---|---|
| Three sample sentences | 57 tokens | 87 tokens | 1.53× |
| Full prompt with facts | 1,677 tokens | 2,490 tokens | +48% |

Rules stay in English in the prompt, and the style guidance and examples are Gujarati. Rules-in-English saves tokens on every turn. Whether it also follows instructions better than an all-Gujarati prompt is untested.

Estimated effect on Groq's 8K tokens-per-minute and 200K per-day limits, taking `docs/agent.md`'s 2,500 tokens per English request plus the 813 extra: about 2.4 requests a minute and 60 a day per model, down from about 3 and 80. A real day of Gujarati calls needs a paid tier. Groq's page is ambiguous about which plan those numbers apply to, so check your account's Limits page.

## 4. Fine-tuning: is it needed, and where?

**Recommendation: don't fine-tune anything yet.** No component has a measured problem that training would fix, and the data isn't ready. Each row below gives the condition that would change that.

| Component | Can it be done? | Verdict | What would change it |
|---|---|---|---|
| **LLM on Groq** | Groq hosts LoRA adapters but doesn't train them. Enterprise tier only, and only `llama-3.1-8b-instant` is listed. **Not gpt-oss** | No | Moving to the enterprise tier and to an 8B model, which is a downgrade to fix a problem not yet shown |
| **LLM on Gemini** | No fine-tuning in the Gemini API or AI Studio, with no plans to return. Supported on Google's enterprise platform only, which means leaving the free AI Studio key | No | Reviewed data, plus a measured style gap prompts can't close |
| **STT** | I found no self-serve training for Saaras. It offers `keyterms` (up to 50) on `saaras:v4`, though the docs disagree on whether that covers streaming and the plugin doesn't expose it. `STTRealtime` has `prompt`, and Deepgram has `keyterm` | No training. Use vocabulary biasing | Name accuracy staying poor on real recordings after biasing. Then ask Sarvam and Deepgram directly |
| **TTS** | Pronunciation dictionaries (`dict_id`) on v3 and v4 Flash. "Instant Voice Cloning" is on the rate card at ₹2 per 1,000 characters, but how to create one and the commercial terms weren't confirmed | Dictionary first | No stock voice reaching the target in listening tests. Then a custom voice from a consenting Gujarati speaker, with their written consent and Sarvam's licence checked |

Why not fine-tune the LLM on the 554 conversations anyway:

1. **Nobody has reviewed them.** Training on unreviewed synthetic Gujarati would bake any mistakes in permanently, and make them harder to see than a line in a prompt.
2. **They carry no tool calls.** This agent's job is calling `prepare_booking` correctly. Tuning on plain dialogue risks degrading exactly that, and the safety rules with it.
3. **The largest failures weren't the model's.** Everything in section 1 was deterministic code, and more training couldn't have fixed any of it.
4. **Prompting is unexhausted.** It costs nothing, takes effect immediately, and can be reversed in a minute.

**Which component would benefit most?** Going by consequences rather than measurements, so treat this as a hypothesis: STT name and number accuracy, because one misheard name breaks a booking while slightly stiff wording doesn't. The listening test will show whether the voice matters more.

### When to revisit

Fine-tune the LLM only when all of these are true:

- Native raters score wording below 3.5 out of 5 on real calls, for reasons they can name.
- Prompt changes have stopped helping that score.
- You have at least 1,000 reviewed examples, preferably from real anonymised calls, including tool calls.
- Tool-call accuracy is measured before and after, and doesn't fall.

## 5. Things to decide

**Outbound calls.** The brief's examples ("હું તમને ... સંપર્ક કરી રહ્યો છું", and receiving a call from ResAssistant) read as outbound, while `CLAUDE.md` says inbound only in v1, citing TRAI's Sept 2026 amendment on AI calls. This work is inbound. Those lines are in the dataset as a style reference (`callback_info`), but nothing places calls. Get a legal view before changing that.

**AI disclosure stays.** The goal is a caller who feels they're talking to a fluent assistant, and the agent still says it's an AI, in the greeting and whenever asked. `CLAUDE.md` requires that on every call, and it's the right call on honesty too. The evals fail any reply claiming to be a person.

**A Gujarat caller can't easily reach this yet.** The number is a free US one, so it's an international call from India. Real use needs an Indian number (Exotel or Plivo, per `CLAUDE.md`), which also lets you check real carrier audio.

**Region.** The agent is in `us-east`, chosen to sit beside Deepgram and Groq, and that can't be changed once created. Sarvam's hosting region isn't stated in the docs I read. If it's in India, every STT and TTS hop crosses the ocean. Measure with `check_providers.py` from the deployed agent; a new agent in `ap-south` may be worth it.

**Cost, as a rough estimate.** STT is ₹0.49 a minute. TTS is ₹3 per 1,000 characters on v3 and ₹1 on v4 Flash. For a two-minute call with 600 spoken characters, that's about ₹2.80 on v3 and ₹1.60 on v4 Flash, so ₹100 of credit lasts roughly 35 to 60 calls. `preemptive_tts` can synthesise replies that get thrown away, so real use may run higher.

## Known limitations

- **Double backchannels interrupt.** "હા હા" is two words, so with partial transcripts it stops the agent where "હા" wouldn't. Raising `min_words` to 3 would stop "ના ના" from interrupting, which is worse.
- **Term biasing does nothing on the default `sarvam` STT**, as the plugin gives it no way in. Only `sarvam-realtime` and Deepgram learn the dish names.
- **Dish names arrive in English** from the menu data, and the LLM renders them in Gujarati. A per-language menu name would need a contract change.
- **Text chats and Telegram voice notes stay English.** `AGENT_LANGUAGE` covers calls only.
- **The sample restaurant is The Saffron Table in Bengaluru.** For a fair test of Gujarati names and places, add a fictional Gujarati restaurant.
- **Thin dataset areas:** 25 elderly, 26 young, 19 formal and 11 heavily mixed conversations, against 554 overall.

## Sources

- Sarvam: [Saaras models](https://docs.sarvam.ai/api-reference-docs/getting-started/models/saaras.md), [streaming STT](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/streaming-api.md), [Bulbul models](https://docs.sarvam.ai/api/getting-started/models/bulbul), [TTS streaming](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api/http-stream.md), [pricing](https://docs.sarvam.ai/api/getting-started/pricing.md)
- LiveKit: [turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/), [Sarvam STT plugin](https://docs.livekit.io/agents/models/stt/plugins/sarvam/), [Sarvam TTS plugin](https://docs.livekit.io/agents/models/tts/plugins/sarvam/)
- Groq: [models](https://console.groq.com/docs/models), [rate limits](https://console.groq.com/docs/rate-limits), [LoRA](https://console.groq.com/docs/lora)
- Google: [Gemini model tuning](https://ai.google.dev/gemini-api/docs/model-tuning)
- Deepgram: [Nova-3 Asia-Pacific expansion](https://deepgram.com/learn/deepgram-nova-3-expands-speech-to-text-support-across-asia-pacific), [language prompting](https://developers.deepgram.com/docs/nova-3-language-prompting.md), [Aug 2026 changelog](https://developers.deepgram.com/changelog/2026/8/4)
- Benchmarks: [IndicGenBench](https://preview.aclanthology.org/setup/2024.acl-long.595), [MILU](https://preview.aclanthology.org/setup/2025.naacl-long.507)
