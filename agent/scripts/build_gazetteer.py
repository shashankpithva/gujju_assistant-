"""Build the list of Gujarat's districts, talukas, villages and towns the survey checks answers against.

    uv run python scripts/build_gazetteer.py --villages <lgd.csv> --towns <urban-local-body.csv>

Sources (both from the Local Government Directory, Ministry of Panchayati Raj, under the Government
Open Data License - India):
- villages, talukas and districts: "List of states, districts, sub-districts and villages along with
  their LGD codes, as of 7 May 2026", as published on dataful.in and mirrored at
  github.com/Meghraj-6093/Indian-state-district-subDistrict-villages (extracted_data/). It includes
  the Vav-Tharad district and the 17 talukas created on 2 October 2025.
- towns and cities: municipal/urban-local-body.csv from github.com/planemad/india-local-government-directory
  (LGD, retrieved 11 March 2022). Towns rarely change; the list is used for their names.

Writes src/agent/places/data/gujarat.csv.gz: one row per place, with the official English name, the
other names it's known by (for matching), and its district and taluka.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

GUJARAT = "24"
OUT = Path(__file__).resolve().parents[1] / "src/agent/places/data/gujarat.csv.gz"

# Census markers, not part of the name people say: census town, outgrowth, part of a village.
_MARKERS = re.compile(r"\s*\((?:ct|og|part|m|m\.? ?corp\.?|ward[^)]*)\)", re.IGNORECASE)
_ANY_BRACKETS = re.compile(r"\s*\([^)]*\)")
_NUMBERED = re.compile(r"\s*no\.?\s*-?\s*\d+\s*$", re.IGNORECASE)  # "Ningala No-2", "Dudhala No.1"
# Town body names that aren't part of the town's name.
_TOWN_WORDS = re.compile(r"\b(seva sadan|kachchh)\b", re.IGNORECASE)
_TOWN_FIXES = {"kaalol": "Kalol", "shahera": "Shehera"}


def tidy(name: str) -> str:
    """Spacing and capitals: "SHAHERA" -> "Shahera", "savli" -> "Savli"; mixed case is kept."""
    name = " ".join(name.replace("( ", "(").split())
    if name.isupper() or name.islower():
        name = name.title()
    return name


def village_names(raw: str) -> tuple[str, list[str]]:
    """The official name without census markers, and the shorter names people say."""
    name = tidy(_MARKERS.sub("", raw))
    names = [name]
    bare = tidy(_ANY_BRACKETS.sub("", name))  # "Rampura (Danta)" is said "Rampura"
    if bare and bare not in names:
        names.append(bare)
    unnumbered = tidy(_NUMBERED.sub("", bare))
    if unnumbered and unnumbered not in names:
        names.append(unnumbered)
    return name, names[1:]


def town_names(raw: str) -> list[str]:
    """ "Porbandar-Chhaya" is two towns; "Himatnagar Seva Sadan" is Himatnagar."""
    raw = _TOWN_WORDS.sub("", raw)
    parts = [tidy(p) for p in re.split(r"\s*-\s*", raw) if p.strip()]
    return [_TOWN_FIXES.get(p.lower(), p) for p in parts]


def build(villages_csv: Path, towns_csv: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    districts: dict[str, str] = {}
    talukas: dict[tuple[str, str], str] = {}
    with villages_csv.open(newline="", encoding="utf-8") as source:
        for r in csv.DictReader(source):
            if r["state_code"].strip() != GUJARAT:
                continue
            district, taluka = tidy(r["district_name"]), tidy(r["sub-district_name"])
            districts[district] = r["district_code"].strip()
            talukas[(district, taluka)] = r["sub-district_code"].strip()
            name, aliases = village_names(r["village_name"])
            rows.append(
                {
                    "kind": "village",
                    "code": r["village_code"].strip(),
                    "name": name,
                    "aliases": "|".join(aliases),
                    "district": district,
                    "taluka": taluka,
                }
            )
    for district, code in sorted(districts.items()):
        rows.append(
            {
                "kind": "district",
                "code": code,
                "name": district,
                "aliases": "",
                "district": district,
                "taluka": "",
            }
        )
    for (district, taluka), code in sorted(talukas.items()):
        rows.append(
            {
                "kind": "taluka",
                "code": code,
                "name": taluka,
                "aliases": "",
                "district": district,
                "taluka": taluka,
            }
        )

    # Towns: placed in the district whose taluka has the town's name, when exactly one does.
    by_taluka_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for district, taluka in talukas:
        by_taluka_name[taluka.lower()].append((district, taluka))
    seen: set[str] = set()
    with towns_csv.open(newline="", encoding="utf-8") as source:
        for r in csv.DictReader(source):
            if r["State Code"].strip() != GUJARAT:
                continue
            for town in town_names(r["Local Body Name"]):
                if town.lower() in seen:
                    continue
                seen.add(town.lower())
                homes = by_taluka_name.get(town.lower(), [])
                district, taluka = homes[0] if len(homes) == 1 else ("", "")
                rows.append(
                    {
                        "kind": "town",
                        "code": r["Local Body Code"].strip(),
                        "name": town,
                        "aliases": "",
                        "district": district,
                        "taluka": taluka,
                    }
                )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--villages", type=Path, required=True, help="the LGD villages CSV (May 2026)")
    parser.add_argument("--towns", type=Path, required=True, help="the LGD urban-local-body.csv")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    rows = build(args.villages, args.towns)
    kinds = Counter(r["kind"] for r in rows)
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=["kind", "code", "name", "aliases", "district", "taluka"])
    writer.writeheader()
    writer.writerows(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0: the same input gives byte-for-byte the same file, so git sees no change.
    with gzip.GzipFile(args.out, "wb", mtime=0) as target:
        target.write(text.getvalue().encode("utf-8"))
    print(f"{args.out}: {dict(kinds)}, {args.out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
