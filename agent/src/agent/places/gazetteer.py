"""Gujarat's districts, talukas, villages and towns, and finding the one a person named.

A name is found by how it sounds (keys.py), so "ખાંભા", "ખંભા" and "Khambha" all find Khambha.
Small differences are allowed: speech-to-text drops a sound now and then, and the person confirms
every name before it's written down (survey/flow.py), so a near miss is caught there.

What the person has already said narrows the search: a taluka with their village in it, or the
district their taluka is in, wins over a place that only sounds as close.

The village question also finds towns and cities ("અમદાવાદ"), and the taluka question also finds a
city that's split into several talukas, said by its own name ("સુરત").
"""

from __future__ import annotations

import csv
import gzip
import io
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from functools import cache, lru_cache
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz, process

from agent.places.keys import SCHWA_RULES, is_gujarati, key, keys, romanize, skeleton
from agent.places.names import (
    DISTRICT_ALIASES,
    DISTRICTS,
    TALUKA_ALIASES,
    TALUKAS,
    TOWN_ALIASES,
    TOWNS,
)
from agent.places.transliterate import to_gujarati

DATA = Path(__file__).parent / "data" / "gujarat.csv.gz"

Kind = Literal["village", "taluka", "district"]
# Below this, a name is "not in the list". 100 is the same sound; a sound or two off in a name of
# average length lands in the high 80s.
MATCH_AT = 82.0
# A place that fits what's already known (a taluka with their village in it) beats one that only
# sounds closer: "લીમડી" from a village in Limbdi taluka is Limbdi, not Govindguru Limdi.
FITS_BONUS = 12.0
# A taluka's name to the village question, or a city's to the taluka question: fine, but a place of
# the kind asked about, with the same name, comes first.
OTHER_KIND = 2.0
# How alike a town's and a district's names must be for the district to be named after the town.
CITY_NAME = 85
# A name found inside a longer answer ("ખાંભા પાસે") rather than as the whole answer.
PART_OF_ANSWER = 3.0
_CANDIDATES = 15  # fuzzy candidates looked at per spelling
_KIND_ORDER = {"town": 0, "village": 1, "taluka": 2, "district": 3}

# Words around a place name that aren't part of it, and endings it may come with ("ખાંભાથી").
_FILLER = {
    "ગામ", "ગામનું", "ગામનો", "શહેર", "તાલુકો", "તાલુકા", "તાલુકાનું", "જિલ્લો", "જીલ્લો", "જિલ્લા",
    "જીલ્લા", "મારું", "મારો", "અમારું", "અમારો", "છે", "તો", "જ", "હા", "ના", "પાસે", "બાજુ", "નજીક",
    "village", "taluka", "district", "city", "near",
}  # fmt: skip
_ENDINGS = ("માંથી", "માં", "થી", "નું", "નો", "ની", "ના", "વાળા")
_SPLIT = re.compile(r"[\s,.;!?।]+")


@dataclass(frozen=True)
class Place:
    kind: str  # "district", "taluka", "village" or "town"
    name: str  # the official English name
    district: str  # "" for a town whose district isn't known
    taluka: str  # "" for a district, or a town whose taluka isn't known
    code: str  # the Local Government Directory's code
    gujarati: str | None = None

    def label(self, gujarati: str | None = None) -> str:
        """As the sheet shows it: "ખાંભા (Khambha)", or the English name alone."""
        local = gujarati or self.gujarati
        return f"{local} ({self.name})" if local and local != self.name else self.name


@dataclass(frozen=True)
class Match:
    kind: Kind  # the question it answers
    places: tuple[Place, ...]  # every place with the name found, the likeliest first
    heard: str  # the person's words for it
    score: float
    said: tuple[str, ...] = ()  # every way the name came through (their words, the LLM's spelling)

    @property
    def place(self) -> Place:
        return self.places[0]

    @property
    def exact(self) -> bool:
        """Their own words sound exactly like the place's own name (not one of its other names)."""
        return is_gujarati(self.heard) and bool(keys(self.heard) & _own_keys(self.place))

    @property
    def spoken(self) -> str:
        """The name read back for a yes: the person's own words when they're the place's name, or
        else the list's name, in Gujarati. "Baroda" is read back as "વડોદરા", "Bhuj" as "કચ્છ", so the
        yes is to the place that goes in the sheet."""
        if self.exact:
            return self.heard
        return self.place.gujarati or to_gujarati(self.place.name)

    @property
    def sheet(self) -> str:
        """For the sheet: "ખાંભા (Khambha)". The Gujarati is the list's, or their words when those are
        the place's name; a village with neither is written in English alone."""
        return self.place.label(self.place.gujarati or (self.heard if self.exact else None))

    @property
    def is_city(self) -> bool:
        return self.place.kind == "town"


@lru_cache(maxsize=4096)
def _own_keys(place: Place) -> frozenset[str]:
    """The keys of a place's own name and its Gujarati name, not of its other names."""
    return frozenset(keys(place.name) | (keys(place.gujarati) if place.gujarati else set()))


def _spelling_closeness(names: Sequence[str], gujarati: str | None, said: Sequence[str]) -> float:
    """How closely a place's names are spelt like what was said, before keys merge sounds: "ધારી"
    is nearer Dhari than Dari, though both have the key "dari"."""
    if gujarati and gujarati in said:
        return 101.0
    heard = {romanize(s, schwa=rule) for s in said for rule in SCHWA_RULES}
    spelt = {romanize(n, schwa=rule) for n in names for rule in SCHWA_RULES}
    return max((fuzz.ratio(h, n) for h in heard for n in spelt), default=0.0)


class _Index:
    """Places by the keys of every name they're known by, with fuzzy search over those keys."""

    def __init__(self, names: Iterable[tuple[str, Place]], *, other_kinds: Sequence[str] = ()) -> None:
        by_key: dict[str, list[Place]] = defaultdict(list)
        self.names: dict[Place, list[str]] = defaultdict(list)  # every name a place is known by
        for text, place in names:
            self.names[place].append(text)
            for k in keys(text):
                if place not in by_key[k]:
                    by_key[k].append(place)
        self._by_key = dict(by_key)
        self._keys = list(self._by_key)
        self._skeletons = [skeleton(k) for k in self._keys]
        self._other_kinds = set(other_kinds)

    def search(self, heard: str) -> dict[str, float]:
        """Every key that sounds like `heard`, with how closely (0-100)."""
        found: dict[str, float] = {}
        for k in keys(heard):
            if k in self._by_key:
                found[k] = 100.0
            shape = skeleton(k)
            for candidate, ratio, i in process.extract(
                k, self._keys, scorer=fuzz.ratio, limit=_CANDIDATES, score_cutoff=60
            ):
                if candidate == k:
                    continue
                same_shape = 100.0 if shape == self._skeletons[i] else fuzz.ratio(shape, self._skeletons[i])
                score = min(99.0, 0.75 * ratio + 0.25 * same_shape)
                found[candidate] = max(found.get(candidate, 0.0), score)
        return found

    def places(self, k: str) -> list[Place]:
        return self._by_key[k]

    def penalty(self, place: Place) -> float:
        return OTHER_KIND if place.kind in self._other_kinds else 0.0


class Gazetteer:
    def __init__(self, places: Sequence[Place]) -> None:
        self.districts = [p for p in places if p.kind == "district"]
        self.talukas = [p for p in places if p.kind == "taluka"]
        self.villages = [p for p in places if p.kind in ("village", "town")]
        # A district named after its city ("Surat", "Ahmedabad" for the town "Ahmadabad"): the city's
        # other names are the district's ("Amdavad", "Baroda"), and its name may be all the taluka a
        # city dweller gives.
        cities: dict[str, Place] = {}
        for town in (v for v in self.villages if v.kind == "town"):
            for d in self.districts:
                if (
                    key(town.name)[:1] == key(d.name)[:1]
                    and fuzz.ratio(key(town.name), key(d.name)) >= CITY_NAME
                ):
                    cities[town.name] = d
        self._village_talukas: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for v in self.villages:
            if v.taluka:
                self._village_talukas[v.name].add((v.district, v.taluka))
        self._indexes: dict[Kind, _Index] = {
            "district": _Index(_district_names(self.districts)),
            "taluka": _Index(
                [*_taluka_names(self.talukas), *_district_names(set(cities.values()))],
                other_kinds=("district",),
            ),
            "village": _Index(
                [*_village_names(self.villages, cities), *_taluka_names(self.talukas)],
                other_kinds=("taluka",),
            ),
        }

    def match(
        self,
        kind: Kind,
        heard: Sequence[str],
        *,
        village: Match | None = None,
        taluka: Match | None = None,
        district: Match | None = None,
    ) -> Match | None:
        """The place a person named, or None if nothing in the list sounds like it.

        `heard` holds the ways the name came through: the Gujarati the person said, and the English
        spelling the LLM gave it. What's already known (`village`, `taluka`, `district`) breaks
        ties toward the place that fits with it.
        """
        index = self._indexes[kind]
        context = (village, taluka, district)
        heard = [" ".join(h.split()) for h in heard if h and h.strip()]
        best: dict[str, float] = {}  # key -> score
        closeness: dict[str, float] = {}
        exact_words: dict[str, str] = {}  # key -> the person's Gujarati words that sound exactly like it
        for text in heard:
            for part, penalty in _parts(text):
                for k, close in index.search(part).items():
                    places = index.places(k)
                    fits = any(self._fits(kind, p, *context) for p in places)
                    score = close - penalty + (FITS_BONUS if fits else 0.0) - min(map(index.penalty, places))
                    if score > best.get(k, -1.0):
                        best[k], closeness[k] = score, close - penalty
                    if close >= 100.0 and is_gujarati(part):
                        exact_words.setdefault(k, part)
            if best and max(closeness.values()) >= 100.0:
                break  # the person's words found it exactly: the LLM's spelling can't do better
        if not best:
            return None
        k = max(best, key=lambda c: (best[c], c in exact_words))
        if closeness[k] < MATCH_AT:
            return None
        words = exact_words.get(k) or next((t for t in heard if is_gujarati(t)), heard[0])
        found = Match(kind, tuple(index.places(k)), words, round(best[k], 1), tuple(heard))
        return self.rank(found, village=village, taluka=taluka, district=district)

    def rank(
        self,
        found: Match,
        *,
        village: Match | None = None,
        taluka: Match | None = None,
        district: Match | None = None,
    ) -> Match:
        """The same name, with the place that fits what's known first: which of the Navagams is meant
        is clearer once the taluka is known."""
        index = self._indexes[found.kind]
        said = found.said or (found.heard,)
        ranked = sorted(
            dict.fromkeys(found.places),
            key=lambda p: (
                not self._fits(found.kind, p, village, taluka, district),
                -round(_spelling_closeness(index.names[p], p.gujarati, said)),
                index.penalty(p),
                _KIND_ORDER.get(p.kind, 9),
                p.name,
            ),
        )
        return replace(found, places=tuple(ranked))

    def _fits(
        self, kind: Kind, place: Place, village: Match | None, taluka: Match | None, district: Match | None
    ) -> bool:
        if kind == "village":
            if taluka is not None:
                return any(_in_taluka(place, t) for t in taluka.places)
            return district is not None and place.district in {d.name for d in district.places}
        if kind == "taluka":
            if district is not None:
                return place.district in {d.name for d in district.places}
            return village is not None and any(self._has(place, v) for v in village.places)
        if taluka is not None:
            return place.name in {t.district for t in taluka.places}
        return village is not None and place.name in {v.district for v in village.places}

    def _has(self, taluka: Place, village: Place) -> bool:
        """Whether a taluka (or a city, for a city's talukas) has a village or town of that name."""
        if taluka.kind == "district":
            return village.district == taluka.name
        if village.kind == "taluka":  # a taluka's own town, said as the village
            return (village.district, village.name) == (taluka.district, taluka.name)
        return (taluka.district, taluka.name) in self._village_talukas.get(village.name, ())

    def village_in_taluka(self, village: Match, taluka: Match) -> bool:
        """Whether any place of the village's name is in any taluka of the taluka's name."""
        return any(self._has(t, v) or _in_taluka(v, t) for v in village.places for t in taluka.places)

    @staticmethod
    def taluka_in_district(taluka: Match, district: Match) -> bool:
        return any(t.district == d.name for t in taluka.places for d in district.places)


def _in_taluka(place: Place, taluka: Place) -> bool:
    if taluka.kind == "district":  # a city's name given as the taluka
        return place.district == taluka.name
    if place.kind == "taluka":
        return (place.district, place.name) == (taluka.district, taluka.name)
    return (place.district, place.taluka) == (taluka.district, taluka.name)


def _parts(text: str) -> list[tuple[str, float]]:
    """The answer to search for, and the less likely pieces of it, each with its penalty: the whole
    answer; without filler ("ખાંભા ગામ"); without an ending ("ખાંભાથી"); one or two of its words."""
    text = " ".join(text.split())
    if not text:
        return []
    found: dict[str, float] = {text: 0.0}
    words = [w for w in _SPLIT.split(text) if w and w.lower() not in _FILLER]
    if words:
        found.setdefault(" ".join(words), 0.0)
    stems = [
        next((w[: -len(e)] for e in _ENDINGS if w.endswith(e) and len(w) > len(e) + 1), w) for w in words
    ]
    if stems != words:
        found.setdefault(" ".join(stems), 1.0)
    if len(stems) > 1:
        for size in (2, 1):
            for i in range(len(stems) - size + 1):
                found.setdefault(" ".join(stems[i : i + size]), PART_OF_ANSWER)
    return list(found.items())


def _district_names(districts: Iterable[Place]) -> Iterable[tuple[str, Place]]:
    for d in districts:
        yield d.name, d
        if d.gujarati:
            yield d.gujarati, d
        for alias in DISTRICT_ALIASES.get(d.name, ()):
            yield alias, d


def _taluka_names(talukas: Iterable[Place]) -> Iterable[tuple[str, Place]]:
    for t in talukas:
        yield t.name, t
        if t.gujarati:
            yield t.gujarati, t
        for alias in TALUKA_ALIASES.get(t.name, ()):
            yield alias, t


def _village_names(villages: Iterable[Place], cities: dict[str, Place]) -> Iterable[tuple[str, Place]]:
    for v in villages:
        yield v.name, v
        if v.gujarati:
            yield v.gujarati, v
        if v.kind == "town":
            for alias in TOWN_ALIASES.get(v.name, ()):
                yield alias, v
            if (district := cities.get(v.name)) is not None:
                for alias in DISTRICT_ALIASES.get(district.name, ()):
                    yield alias, v


@cache
def gujarat() -> Gazetteer:
    """Every place in Gujarat, loaded once per process (well under a second: run it at startup)."""
    return Gazetteer(load(DATA))


def load(path: Path) -> list[Place]:
    with gzip.open(path, "rb") as packed:
        rows = list(csv.DictReader(io.TextIOWrapper(packed, encoding="utf-8")))
    district_names = {
        k: d for d in DISTRICTS for name in (d, *DISTRICT_ALIASES.get(d, ())) for k in keys(name)
    }
    places: list[Place] = []
    for row in rows:
        kind, name, district = row["kind"], row["name"], row["district"]
        if kind == "district":
            gujarati = DISTRICTS.get(name)
        elif kind == "taluka":
            gujarati = TALUKAS.get(name)
        elif kind == "town":
            gujarati = TOWNS.get(name) or TALUKAS.get(name) or DISTRICTS.get(name)
            district = district or district_names.get(key(name), "")  # "Ahmadabad" is in Ahmedabad
        else:
            gujarati = None
        places.append(Place(kind, name, district, row["taluka"], row["code"], gujarati))
        for alias in filter(None, row["aliases"].split("|")):  # "Rampura (Danta)" is said "Rampura"
            places.append(Place(kind, alias, district, row["taluka"], row["code"], None))
    return places
