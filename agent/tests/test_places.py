"""The list of Gujarat's places, and finding the one a person named, however they said it."""

import pytest

from agent.places import gujarat, load_places
from agent.places.gazetteer import DATA, load
from agent.places.keys import key, keys, romanize
from agent.places.names import DISTRICT_ALIASES, DISTRICTS, TALUKA_ALIASES, TALUKAS, TOWN_ALIASES, TOWNS
from agent.places.transliterate import to_gujarati


@pytest.fixture(scope="module")
def places():
    return gujarat()


# The list itself ------------------------------------------------------------------------------------


def test_the_list_has_every_district_and_taluka_of_gujarat(places):
    assert len(places.districts) == 34  # with Vav-Tharad, made in 2025
    assert len(places.talukas) == 299  # with the 17 talukas made on 2 October 2025
    assert len(places.villages) > 19_000
    assert {"Vav-Tharad", "Kachchh", "Dangs"} <= {d.name for d in places.districts}
    assert {"Dharnidhar", "Raah", "Ambika"} <= {t.name for t in places.talukas}  # three of the new ones


def test_every_gujarati_name_and_alias_is_for_a_place_in_the_list(places):
    districts = {d.name for d in places.districts}
    talukas = {t.name for t in places.talukas}
    towns = {v.name for v in places.villages if v.kind == "town"}
    assert set(DISTRICTS) == districts  # every district has its Gujarati name
    assert set(TALUKAS) == talukas  # and every taluka
    assert set(DISTRICT_ALIASES) <= districts
    assert set(TALUKA_ALIASES) <= talukas
    assert set(TOWNS) | set(TOWN_ALIASES) <= towns


def test_every_place_is_in_a_district_and_a_taluka_that_exist(places):
    districts = {d.name for d in places.districts}
    talukas = {(t.district, t.name) for t in places.talukas}
    assert all((t.district in districts) for t in places.talukas)
    villages = [v for v in places.villages if v.kind == "village"]
    assert all((v.district, v.taluka) in talukas for v in villages)


def test_the_data_file_loads_with_its_aliases():
    rows = load(DATA)
    assert any(p.name == "Rampura" and p.kind == "village" for p in rows)  # "Rampura (Danta)" as said


def test_the_list_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("PLACE_CHECK", "off")
    assert load_places() is None
    monkeypatch.setenv("PLACE_CHECK", "on")
    assert load_places() is gujarat()


# How a name sounds ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gujarati", "english"),
    [
        ("ખાંભા", "Khambha"),
        ("અમરેલી", "Amreli"),
        ("ભાવનગર", "Bhavnagar"),
        ("ગાંધીનગર", "Gandhinagar"),
        ("ઢોલરવા", "Dholarva"),
        ("પીપળીયા", "Pipalia"),
        ("દિયોદર", "Deodar"),
        ("સુરેન્દ્રનગર", "Surendranagar"),
        ("જૂનાગઢ", "Junagadh"),
        ("વડોદરા", "Vadodara"),
    ],
)
def test_a_gujarati_name_and_its_english_spelling_sound_the_same(gujarati, english):
    assert key(english) in keys(gujarati)


def test_spellings_that_differ_only_in_how_theyre_written_sound_the_same():
    assert keys("ખાંભા") & keys("ખંભા")  # vowel length
    assert keys("પીપળીયા") & keys("પિપળિયા")
    assert key("Kutch") != key("Kachchh")  # a different name: that's what aliases are for


def test_the_short_a_gujarati_doesnt_say_is_dropped_each_way():
    assert romanize("અમરેલી") == "amreli"
    assert romanize("ઢોલરવા", schwa="right") == "dholarva"
    assert romanize("ગાંધીનગર", schwa="keep") == "gandhinagar"


def test_an_english_name_is_spelt_in_gujarati_for_the_voice():
    assert to_gujarati("Dholarva") == "ધોલર્વા"
    assert to_gujarati("Pipalia") == "પિપલિયા"
    assert to_gujarati("Khambha") == "ખંભા"
    assert to_gujarati("Amreli") == "અમ્રેલી"
    assert to_gujarati("Savar Kundla") == "સવર કુંદ્લા"
    for name in ("Dholarva", "Pipalia", "Mandavad", "Kheralu", "Shiyal Bet"):
        assert key(name) in keys(to_gujarati(name))  # it says the same name


# Finding a place --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "said", "name"),
    [
        ("village", "ખાંભા", "Khambha"),
        ("village", "ખંભા", "Khambha"),
        ("village", "ઢોલરવા", "Dholarva"),
        ("village", "અમદાવાદ", "Ahmadabad"),  # a city, to the village question
        ("village", "બરોડા", "Vadodara"),
        ("village", "મારું ગામ ખાંભા છે", "Khambha"),
        ("village", "ખાંભાથી", "Khambha"),
        ("taluka", "દિયોદર", "Deodar"),
        ("taluka", "રાજપીપળા", "Nandod"),  # the taluka, by its town
        ("taluka", "સુરત", "Surat"),  # a city split into several talukas, by its own name
        ("taluka", "કુંડલા", "Savar Kundla"),
        ("district", "કચ્છ", "Kachchh"),
        ("district", "મેહસાણા", "Mahesana"),
        ("district", "થરાદ", "Vav-Tharad"),
        ("district", "ભુજ", "Kachchh"),  # the district, by its town
    ],
)
def test_a_place_is_found_however_its_said(places, kind, said, name):
    found = places.match(kind, [said])
    assert found is not None and found.place.name == name


@pytest.mark.parametrize(("kind", "said"), [("village", "પ્લાસ્ટિક"), ("taluka", "કચ્છ"), ("district", "ખાંભા")])
def test_a_name_thats_not_in_the_list_isnt_found(places, kind, said):
    assert places.match(kind, [said]) is None


def test_the_english_spelling_finds_what_the_gujarati_doesnt(places):
    assert places.match("taluka", ["દેવદર"]).score < 100  # speech-to-text's spelling: a near miss
    found = places.match("taluka", ["દેવદર", "Deodar"])
    assert found.place.name == "Deodar" and found.score == 100


def test_the_name_read_back_is_theirs_or_the_lists(places):
    own = places.match("village", ["ઢોલરવા"])
    assert own.exact and own.spoken == "ઢોલરવા" and own.sheet == "ઢોલરવા (Dholarva)"
    other_name = places.match("district", ["ભુજ"])
    assert not other_name.exact and other_name.spoken == "કચ્છ" and other_name.sheet == "કચ્છ (Kachchh)"
    near = places.match("taluka", ["દેવદર"])
    assert near.spoken == "દિયોદર"  # not their words: the list's name is what they confirm


def test_the_closer_spelling_wins_between_places_that_sound_alike(places):
    assert places.match("village", ["ધારી"]).place.name == "Dhari"  # not Dari, though both are "dari"


def test_what_is_known_picks_the_place(places):
    village = places.match("village", ["સિયાણી"])  # a village in Limbdi taluka
    assert places.match("taluka", ["લીમડી"]).place.name == "Govindguru Limdi"
    assert places.match("taluka", ["લીમડી"], village=village).place.name == "Limbdi"
    mandvi = places.match("taluka", ["માંડવી"])
    surat = places.match("district", ["સુરત"])
    assert {p.district for p in mandvi.places} == {"Kachchh", "Surat"}
    assert places.rank(mandvi, district=surat).place.district == "Surat"


def test_whether_places_go_together(places):
    khambha = places.match("village", ["ખાંભા"])
    assert places.village_in_taluka(khambha, places.match("taluka", ["ખાંભા"]))
    assert not places.village_in_taluka(khambha, places.match("taluka", ["ગોંડલ"]))
    assert places.taluka_in_district(places.match("taluka", ["ધારી"]), places.match("district", ["અમરેલી"]))
    assert not places.taluka_in_district(places.match("taluka", ["ધારી"]), places.match("district", ["કચ્છ"]))


def test_finding_a_place_is_quick(places):
    import time

    started = time.perf_counter()
    for said in ("ખાંભા", "ઢોલરવા", "દેવદર", "પ્લાસ્ટિક", "મારું ગામ ખાંભા છે"):
        places.match("village", [said])
    assert time.perf_counter() - started < 0.5  # a few milliseconds each, in the middle of a call
