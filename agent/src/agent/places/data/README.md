# Gujarat's places

`gujarat.csv.gz` is the list the survey checks each village, taluka and district against: 34 districts, 299 talukas, 19,105 villages and 168 towns. Each row has the place's kind (`district`, `taluka`, `village` or `town`), its Local Government Directory code, its official English name, other names it's said by (for matching only), and its district and taluka.

## Sources

Contains data from the **Local Government Directory (LGD), Ministry of Panchayati Raj, Government of India**, under the [Government Open Data License – India](https://www.data.gov.in/Godl). The data is used as published; nothing here is endorsed by the Ministry.

- **Districts, talukas and villages:** "List of states, districts, sub-districts and villages along with their LGD codes, as of 7 May 2026", as published on dataful.in and mirrored at [Meghraj-6093/Indian-state-district-subDistrict-villages](https://github.com/Meghraj-6093/Indian-state-district-subDistrict-villages) (`extracted_data/`). It includes the Vav-Tharad district and the 17 talukas made on 2 October 2025.
- **Towns and cities:** `municipal/urban-local-body.csv` from [planemad/india-local-government-directory](https://github.com/planemad/india-local-government-directory), the LGD's list of urban local bodies as retrieved on 11 March 2022. Town names rarely change.

The Gujarati names of districts, talukas and towns, and the other names people use for them ("Baroda", "Kutch", "Rajpipla"), are in [names.py](../names.py), written by hand.

## Updating it

Download the two CSVs, then rebuild:

```sh
uv run python scripts/build_gazetteer.py --villages <villages.csv> --towns <urban-local-body.csv>
uv run pytest tests/test_places.py
```

The same input gives a byte-identical file, so git shows a change only when the list did. When a new district or taluka appears, the tests ask for its Gujarati name in `names.py`.
