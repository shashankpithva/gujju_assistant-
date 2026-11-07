"""Native-speaker review of the dataset: a spreadsheet out, verdicts back in.

    uv run python scripts/gujarati/review_sheet.py export review.csv
    uv run python scripts/gujarati/review_sheet.py export review.csv --category regional
    uv run python scripts/gujarati/review_sheet.py import review.csv --reviewer "Name, Rajkot"

Export opens in Excel or Google Sheets. Reviewers fill in `verdict` (ok, fix or reject) and, for fix,
`suggestion`. Import records their verdicts in data/gujarati/reviews.jsonl, and the next build shows
them in each record's provenance. Only a person's verdict ever changes "pending".

A "fix" doesn't change the conversation: edit it in data/gujarati/source/ and rebuild. It gets a new
id then, as it's now different text that hasn't been reviewed.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/gujarati/conversations.jsonl"
REVIEWS = ROOT / "data/gujarati/reviews.jsonl"
VERDICTS = {"ok", "fix", "reject"}
COLUMNS = ["id", "category", "region", "conversation", "verdict", "suggestion"]


def records() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]


def as_text(record: dict) -> str:
    who = {"caller": "ફોન કરનાર", "agent": "એજન્ટ"}
    return "\n".join(f"{who[turn['role']]}: {turn['text']}" for turn in record["turns"])


def export(path: Path, category: str | None) -> int:
    pending = [r for r in records() if r["provenance"]["native_review"] == "pending"]
    if category:
        pending = [r for r in pending if r["category"] == category]
    with path.open("w", encoding="utf-8-sig", newline="") as out:  # the BOM keeps Excel on UTF-8
        writer = csv.writer(out)
        writer.writerow(COLUMNS)
        for record in pending:
            writer.writerow([record["id"], record["category"], record["region"], as_text(record), "", ""])
    print(f"{len(pending)} conversations to review in {path}")
    return 0


def import_verdicts(path: Path, reviewer: str) -> int:
    known = {r["id"] for r in records()}
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            verdict = row["verdict"].strip().lower()
            if not verdict:
                continue
            if verdict not in VERDICTS:
                print(f"{row['id']}: verdict must be one of {sorted(VERDICTS)}, got {verdict!r}")
                return 1
            if row["id"] not in known:
                print(f"{row['id']}: no such conversation (was its text changed?)")
                return 1
            rows.append(
                {"id": row["id"], "verdict": verdict, "suggestion": row["suggestion"], "reviewer": reviewer}
            )
    with REVIEWS.open("a", encoding="utf-8", newline="\n") as out:
        out.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    print(f"{len(rows)} verdicts saved. Run scripts/gujarati/build_dataset.py to apply them.")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("file", type=Path)
    parser.add_argument("--category")
    parser.add_argument("--reviewer", help="required for import: who reviewed, and where they're from")
    args = parser.parse_args()
    if args.action == "export":
        return export(args.file, args.category)
    if not args.reviewer:
        parser.error("import needs --reviewer: every verdict has to say whose it is")
    return import_verdicts(args.file, args.reviewer)


if __name__ == "__main__":
    sys.exit(main())
