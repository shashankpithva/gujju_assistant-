"""Build the Gujarati conversation dataset from the hand-written source files.

    uv run python scripts/gujarati/build_dataset.py            # write data/gujarati/conversations.jsonl
    uv run python scripts/gujarati/build_dataset.py --check    # fail if the output is out of date

Source format (data/gujarati/source/*.txt): "%key=value ..." sets a file's defaults, "@key=value ..."
overrides them for the next conversation, and "C:" / "A:" lines are the turns. A blank line ends a
conversation. Agent lines go through the same style rules as the live agent (gujarati/style.py);
anything that breaks one stops the build, unless the line is deliberately not Gujarati (lang=).

The dataset is synthetic. Every record says so, and native_review stays "pending" until a person
has reviewed it: see docs/gujarati/README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from agent.gujarati.style import check_line

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/gujarati/source"
OUTPUT = ROOT / "data/gujarati/conversations.jsonl"
REVIEWS = ROOT / "data/gujarati/reviews.jsonl"
MIN_CONVERSATIONS = 500
# The most any one opening sentence may start, as a share of all agent lines. "કોઈ વાંધો નહીં." fits
# a lot of moments, but a dataset leaning on one phrase teaches the agent to sound like a recording.
MAX_OPENING_SHARE = 0.04

FIELDS = ("category", "register", "speaker", "region", "mix", "lang")
ALLOWED = {
    "register": {"formal", "neutral", "informal"},
    "speaker": {"adult", "elderly", "young"},
    "mix": {"none", "light", "heavy"},
    "lang": {"gu", "en", "hi"},
}


def parse_settings(line: str) -> dict[str, str]:
    settings = dict(pair.split("=", 1) for pair in line[1:].split())
    for key, value in settings.items():
        if key not in FIELDS:
            raise ValueError(f"unknown setting {key!r} in {line!r}")
        if key in ALLOWED and value not in ALLOWED[key]:
            raise ValueError(f"bad value {value!r} for {key} in {line!r}")
    return settings


def parse(path: Path) -> list[dict]:
    defaults = {"lang": "gu"}
    overrides: dict[str, str] = {}
    turns: list[dict] = []
    conversations: list[dict] = []

    def finish() -> None:
        nonlocal turns, overrides
        if turns:
            conversations.append({**defaults, **overrides, "turns": turns, "file": path.name})
        turns, overrides = [], {}

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            finish()
        elif line.startswith("#"):
            continue
        elif line.startswith("%"):
            defaults.update(parse_settings(line))
        elif line.startswith("@"):
            overrides = parse_settings(line)
        elif line.startswith(("C:", "A:")):
            role = "caller" if line[0] == "C" else "agent"
            turns.append({"role": role, "text": line[2:].strip()})
        else:
            raise ValueError(f"{path.name}: can't read {line!r}")
    finish()
    return conversations


def stable_id(conversation: dict) -> str:
    """Stays the same when conversations move or get added, so reviews stay attached."""
    text = "\n".join(turn["text"] for turn in conversation["turns"])
    return f"gu-{hashlib.sha1(text.encode()).hexdigest()[:10]}"


def load_reviews() -> dict[str, dict]:
    """The latest native-speaker review of each conversation, if any."""
    if not REVIEWS.exists():
        return {}
    reviews = {}
    for line in REVIEWS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            review = json.loads(line)
            reviews[review["id"]] = review
    return reviews


def record(conversation: dict, reviews: dict[str, dict]) -> dict:
    rid = stable_id(conversation)
    review = reviews.get(rid)
    region = conversation["region"]
    return {
        "id": rid,
        "category": conversation["category"],
        "register": conversation["register"],
        "speaker": conversation["speaker"],
        "region": region,
        "mix": conversation["mix"],
        "turns": conversation["turns"],
        "provenance": {
            "source": "synthetic_llm_authored",
            "author_model": "claude-opus-5-5",
            "real_speech": False,
            "region_verified": False if region != "standard" else None,
            "native_review": review["verdict"] if review else "pending",
            "reviewer": review.get("reviewer") if review else None,
        },
    }


def lint(conversation: dict) -> list[str]:
    problems = []
    if conversation["turns"][0]["role"] != "caller":
        problems.append("starts with the agent")
    for a, b in zip(conversation["turns"], conversation["turns"][1:], strict=False):
        if a["role"] == b["role"]:
            problems.append(f"two {a['role']} turns in a row: {a['text']}")
    if conversation["lang"] != "gu":
        return problems  # a reply in English or Hindi, on purpose
    for turn in conversation["turns"]:
        if turn["role"] == "agent":
            problems += [f"{problem} | {turn['text']}" for problem in check_line(turn["text"])]
    return problems


def build() -> tuple[list[dict], list[str]]:
    reviews = load_reviews()
    records, problems, seen = [], [], {}
    for path in sorted(SOURCE.glob("*.txt")):
        for conversation in parse(path):
            for problem in lint(conversation):
                problems.append(f"{path.name}: {problem}")
            item = record(conversation, reviews)
            if item["id"] in seen:
                problems.append(f"{path.name}: same as a conversation in {seen[item['id']]}")
            seen[item["id"]] = path.name
            records.append(item)
    return records, problems + repetition_problems(records)


def opening_sentence(line: str) -> str:
    return re.split(r"(?<=[.?!])\s", line)[0]


def repetition_problems(records: list[dict]) -> list[str]:
    lines = [t["text"] for r in records for t in r["turns"] if t["role"] == "agent"]
    limit = MAX_OPENING_SHARE * len(lines)
    counts = Counter(opening_sentence(line) for line in lines)
    return [f"opens {n} of {len(lines)} agent lines: {s}" for s, n in counts.most_common() if n > limit]


def as_jsonl(records: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)


def report(records: list[dict]) -> None:
    turns = sum(len(r["turns"]) for r in records)
    print(f"{len(records)} conversations, {turns} turns")
    for field in ("category", "register", "speaker", "region", "mix"):
        counts = Counter(r[field] for r in records)
        print(f"  {field}: " + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    reviewed = Counter(r["provenance"]["native_review"] for r in records)
    print("  native review: " + ", ".join(f"{k} {v}" for k, v in reviewed.most_common()))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the output is out of date")
    args = parser.parse_args()
    records, problems = build()
    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} problems")
        return 1
    if len(records) < MIN_CONVERSATIONS:
        print(f"only {len(records)} conversations; at least {MIN_CONVERSATIONS} are needed")
        return 1
    text = as_jsonl(records)
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if re.sub(r"\r\n", "\n", current) != text:
            print("data/gujarati/conversations.jsonl is out of date: run scripts/gujarati/build_dataset.py")
            return 1
    else:
        OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    report(records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
