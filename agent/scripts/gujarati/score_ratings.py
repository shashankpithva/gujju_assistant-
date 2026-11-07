"""Turn native speakers' ratings into a decision: which voice, and did the rewrite help?

    uv run python scripts/gujarati/score_ratings.py path/to/ratings-*.json

Reads clips.json from the audition, plus each person's ratings file. Only people who said Gujarati
is their first language are counted. With fewer than MIN_RATERS of them the output says so, as a
ranking from one or two people is an opinion, not a result.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from audio import CACHE

MIN_RATERS = 5
# A difference of means smaller than this isn't worth changing a voice for, however it ranks.
MEANINGFUL_DIFFERENCE = 0.3


def mean_and_margin(scores: list[float]) -> tuple[float, float]:
    """The mean and its rough 95% margin of error."""
    mean = statistics.fmean(scores)
    margin = 1.96 * statistics.stdev(scores) / math.sqrt(len(scores)) if len(scores) > 1 else float("inf")
    return mean, margin


def load(paths: list[Path], clips: dict[str, dict]) -> tuple[list[dict], int, list[str]]:
    rows, natives, skipped = [], 0, []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("native"):
            skipped.append(data.get("rater") or path.name)
            continue
        natives += 1
        for rating in data["ratings"]:
            clip = clips.get(rating["clip"])
            if clip:
                rows.append({**clip, **rating, "rater": data.get("rater"), "from": data.get("from")})
    return rows, natives, skipped


def voice_table(rows: list[dict]) -> list[tuple]:
    grouped = defaultdict(list)
    for row in rows:
        if row["kind"] == "voice" and row["natural"]:
            grouped[(row["voice"], row["pace"])].append(row)
    table = []
    for (voice, pace), group in grouped.items():
        natural, margin = mean_and_margin([r["natural"] for r in group])
        said = [r["pronunciation"] for r in group if r["pronunciation"]]
        pronunciation = statistics.fmean(said) if said else float("nan")
        table.append((natural, margin, pronunciation, voice, pace, len(group)))
    return sorted(table, reverse=True)


def comparison(rows: list[dict]) -> dict[str, dict[str, list[int]]]:
    moments: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"before": [], "after": []})
    for row in rows:
        if row["kind"] in ("before", "after") and row["natural"]:
            moments[row["moment"]][row["kind"]].append(row["natural"])
    return moments


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("ratings", nargs="+", type=Path)
    parser.add_argument("--clips", type=Path, default=CACHE / "audition/clips.json")
    args = parser.parse_args()
    clips = {c["clip"]: c for c in json.loads(args.clips.read_text(encoding="utf-8"))}
    rows, natives, skipped = load(args.ratings, clips)
    print(f"{natives} native speakers counted" + (f"; left out: {', '.join(skipped)}" if skipped else ""))
    if natives < MIN_RATERS:
        print(f"Fewer than {MIN_RATERS} native speakers: treat this as a first impression, not a result.")

    table = voice_table(rows)
    if table:
        print("\nVoices (1 machine, 5 human), best first")
        print(f"{'natural':>8} {'±':>5} {'pronun.':>8}  voice")
        for natural, margin, pronunciation, voice, pace, count in table:
            print(f"{natural:8.2f} {margin:5.2f} {pronunciation:8.2f}  {voice} at {pace} ({count} ratings)")
        if len(table) > 1 and table[0][0] - table[1][0] < MEANINGFUL_DIFFERENCE:
            print(f"The top two are within {MEANINGFUL_DIFFERENCE}: no clear winner, prefer the cheaper one.")

    moments = comparison(rows)
    if moments:
        print("\nBefore and after (natural, 1 to 5)")
        for moment, scores in moments.items():
            if scores["before"] and scores["after"]:
                before, after = statistics.fmean(scores["before"]), statistics.fmean(scores["after"])
                print(f"  {moment:14} {before:.2f} -> {after:.2f}  ({after - before:+.2f})")

    notes = [(r["clip"], r["note"]) for r in rows if r.get("note")]
    if notes:
        print("\nNotes (add wrong pronunciations to LEXICON in gujarati/speech.py):")
        for clip, note in notes:
            print(f"  {clip}: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
