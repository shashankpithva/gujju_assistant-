"""Scores from the Gujarati evals, by metric and by LLM, from evals/results/gujarati.jsonl.

uv run python scripts/gujarati/eval_report.py
uv run python scripts/gujarati/eval_report.py --latest      # only each scenario's last run
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[2] / "evals/results/gujarati.jsonl"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args()
    if not RESULTS.exists():
        print("No results yet: run uv run pytest evals/test_gujarati.py first.")
        return 1
    rows = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.latest:
        rows = list({(r["model"], r["id"]): r for r in rows}.values())
    by_model = defaultdict(list)
    for row in rows:
        by_model[row["model"]].append(row)
    for model, runs in by_model.items():
        print(f"\n{model}: {sum(r['passed'] for r in runs)}/{len(runs)} passed")
        by_metric = defaultdict(list)
        for run in runs:
            by_metric[run["metric"]].append(run)
        for metric, group in sorted(by_metric.items()):
            passed = sum(r["passed"] for r in group)
            print(f"  {metric:14} {passed:3d}/{len(group):3d}  {100 * passed / len(group):5.1f}%")
        styles = Counter(item.split(":")[0] for r in runs for item in r["style"])
        print(f"  style problems: {dict(styles) or 'none'}")
        print(f"  repeated openers: {sum(r['repeated_openers'] for r in runs)}")
        print(f"  median seconds per scenario: {statistics.median(r['seconds'] for r in runs):.1f}")
        failed = [r for r in runs if not r["passed"]]
        for run in failed[:12]:
            print(f"    FAIL {run['id']}: {run['failures'][0].splitlines()[0][:120]}")
        if len(failed) > 12:
            print(f"    ...and {len(failed) - 12} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
