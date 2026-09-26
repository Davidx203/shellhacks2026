# Anders G: Geo Lead

**Your mission:** Give every project a location and a confidence score, find every GPC and DESC pair within 25 miles, rank them, and compute the cost numbers for the top opportunities. You are the brain of the app.

Read `00_TEAM_CONTRACT.md` first. Your output files (`projects.csv`, `overlaps.csv`, `briefs.csv`) are defined there.

## You hand off to

* **David P** loads your three CSVs into the database. Tell them in chat every time you push new versions.
* **Luis D** gets your list of `low` and `unmatched` projects to verify by hand.

## You receive from

* **Luis D:** `data/interim/projects_raw.csv`
* **David P:** `data/fixtures/` built from the starter spreadsheet. Use it for testing before real data arrives.

## Background you need

* Each project connects two substations (endpoint A and endpoint B), or sits at one substation. Its **center point** is the midpoint of the two, or the single point if only one is found.
* **Geographic overlap:** two projects from different utilities whose center points are **under 25 miles apart**. This is the primary signal.
* **Timeline overlap:** how close their in service dates are. This is a secondary signal.
* **Right of way (ROW):** the strip of land a power line needs. Bigger voltage means a wider strip. Sharing it is the main land savings.
* Dominion Energy South Carolina used to be called **SCE&G**, so OpenStreetMap often still tags its substations that way.

## Task list

### Block 1 (Hour 0 to 3): Overlap engine against the fixtures

**Start here, before real data exists.** File: `geo/overlap.py`

```python
from math import radians, sin, cos, asin, sqrt

def haversine_mi(lat1, lon1, lat2, lon2):
    R = 3958.8  # Earth radius in miles
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))
```

Compare every GPC project against every DESC project (about 208 × 44 = 9,000 pairs, which is instant in Python). Keep pairs under 25 miles.

**Test:** run against `data/fixtures/projects.csv`. You must reproduce the starter sheet's distances:

| Pair | Expected `distance_mi` | Expected `time_gap_days` |
| --- | --- | --- |
| DESC_2 + GPC_1 | 4.09 | 3074 |
| DESC_3 + GPC_2 | 5.65 | 152 |
| DESC_3 + GPC_3 | 7.55 | 517 |
| DESC_1 + GPC_1 | 8.01 | 3074 |
| DESC_5 + GPC_2 | 14.34 | 365 |
| DESC_5 + GPC_3 | 14.81 | 730 |

Put this in `geo/test_overlap.py`. If all 6 match, your math is right. Heads up: two dates in the starter sheet are Excel serial numbers (`45809` is 2025-06-01, `45778` is 2025-05-01). David P converts these when building fixtures.

### Block 2 (Hour 3 to 6): Ranking

File: `geo/rank.py`

```
distance_score = 1 - (distance_mi / 25)
time_score     = max(0, 1 - time_gap_days / 1825)     # fades to 0 at 5 years
voltage_score  = 1 if voltage_match else 0
confidence     = min(confidence_gpc, confidence_desc)

score = (0.6 * distance_score + 0.3 * time_score + 0.1 * voltage_score) * (0.5 + 0.5 * confidence)
```

The confidence multiplier means a shaky location can never top the list. Sort by `score`, assign `rank` and `overlap_id` in that order. Keep the weights at the top of the file as named constants, because judges may ask why you chose them. Be ready to explain: "Distance matters most because it's the challenge's primary signal; timing is secondary."

### Block 3 (Hour 3 to 10): Geocoder

File: `geo/geocode.py`

**Step 1: pull every substation once and cache it.** Don't query per project. One query covering Georgia and South Carolina:

```
[out:json][timeout:120];
nwr["power"="substation"](30.3,-85.7,35.3,-78.5);
out center tags;
```

`out center` gives polygon substations a single center point. Send it to `https://overpass-api.de/api/interpreter`, convert the result to GeoJSON, and save to `data/cache/substations_ga_sc.geojson`. Load from the cache after that. Overpass rate limits, so don't rerun it in a loop.

**Step 2: match each endpoint name to a substation.**
* Normalize both sides: uppercase, strip `SUB`, `SUBSTATION`, `PRIMARY`, `(SAV)`, `#5`, and punctuation
* Use `rapidfuzz.fuzz.token_set_ratio` to compare against each substation's `name` tag
* Take the best candidate. If the best score is below 70, mark the endpoint as unmatched

### Block 4 (Hour 10 to 12): Confidence score

File: `geo/confidence.py`. Score each endpoint match from 0 to 1:

| Check | Weight | How |
| --- | --- | --- |
| Name similarity | 0.5 | `token_set_ratio / 100` |
| Operator tag matches | 0.3 | GPC: tag contains `Georgia Power` or `Southern`. DESC: `Dominion`, `SCE&G`, or `South Carolina Electric`. Missing tag scores 0.15 |
| In the expected state | 0.2 | GPC endpoint in GA, DESC endpoint in SC. Use a rough lat/lon check or the state tag. Border substations like Thurmond Dam get partial credit |

**Bonus check:** if both endpoints are found and Luis D extracted `length_mi`, compare it to the straight line distance between A and B. If they are wildly different (endpoints 80 miles apart for a 5 mile line), knock the confidence down hard. This catches the "same name, wrong county" trap the challenge warns about.

Project `confidence` is the average of its endpoints. Assign `confidence_tier` using the thresholds in the contract.

**At CP2:** send Luis D the list of `low` and `unmatched` projects, **sorted by distance to the GA and SC border**, closest first.

### Block 5 (Hour 12 to 20): Run the full pipeline

File: `geo/run_all.py` runs geocode, confidence, overlap, rank, and cost in order and writes all three processed CSVs. Rerun it whenever Luis D pushes new data or corrections.

Sanity checks to post in chat:
* How many projects have coordinates, per utility and per tier
* How many overlaps under 25 miles. **The challenge says most projects will not overlap.** If you find hundreds, something is wrong (probably a bad match placing many projects at one point)
* The top 5 overlaps, by name. Eyeball them: do they make sense on a map?

### Block 6 (Hour 20 to 26): Cost estimate (bonus points)

File: `geo/cost.py`. For the top 10 overlaps:

```
row_width_ft  = {46: 50, 115: 100, 230: 150, 500: 200}[voltage]   # nearest match
shared_acres  = shared_corridor_mi * 5280 * row_width_ft / 43560
savings_usd   = shared_acres * land_cost_per_acre_usd
```

Defaults: `shared_corridor_mi` = the shorter project's `length_mi`, capped at 5 (or 2 if unknown). `land_cost_per_acre_usd` = 10,000.

**Every number here is an assumption, and we say so.** Write each one in plain English in `assumptions_note`. David P turns these into sliders. Where DESC gives `est_cost_usd`, include it as context ("this project alone is budgeted at $11.7M").

## Phase 2 preview (only after CP3)

You will own the **Shared Crew Router**, which uses the Google Directions API to calculate the travel time and distance a shared crew would save moving between paired sites. It adds a `mobilization_savings` number to `briefs.csv`.

## Your definition of done

* [ ] `test_overlap.py` passes all 6 starter pairs
* [ ] Every project in `projects.csv` has a `confidence_tier`
* [ ] `overlaps.csv` is ranked, and the top 5 make sense to a human looking at the map
* [ ] `briefs.csv` has at least the top 3 overlaps, with every assumption written out
