# Luis D: Data Lead

**Your mission:** Turn both utilities' reports into one clean table, `data/interim/projects_raw.csv`, that matches the contract exactly. Everything downstream depends on your output, so **get a rough version out early** and improve it, rather than holding a perfect version until late.

Read `00_TEAM_CONTRACT.md` first. Your output columns are defined there.

## You hand off to

* **Anders G** reads `data/interim/projects_raw.csv`. Tell them in chat every time you push a new version.
* **David P** will show your `project_name`, `in_service_date`, `length_mi`, and `est_cost_usd` in the app, so clean names matter.

## You receive from

* **Anders G** sends you a list of `low` and `unmatched` projects to check by hand (after CP2).

## Background you need

* A **substation** is a fenced yard of electrical equipment where power lines meet. Most projects are named after the substations at each end, for example "Okatie to Bluffton 115 kV rebuild."
* **kV** (kilovolts) describes the size of a line. Common values here: 46, 115, 230, 500.
* The **in service date** is when the project is expected to be finished. Georgia Power calls it the **Need Date**.
* Georgia Power writes names like `SAV: GOSHEN (SAV) - MCINTOSH 115KV LINE REBUILD`. `SAV:` means the Savannah area. Dominion writes names like `Okatie-Bluffton 115 kV: Rebuild`.

## Task list

### Block 1 (Hour 0 to 3): Get set up

1. Copy the raw files into `data/raw/`:
   * Rename `2025_IRP_Volume_3_PUBLIC_DISCLOSURE.pdf` to `gpc_irp_vol3.txt` (it is really a text file)
   * Unzip `2024-2028-2million-and-above-project-descriptions.pdf` into `data/raw/desc_pages/` (it is really a zip)
2. Open a few pages of each and get a feel for the patterns before writing code.

### Block 2 (Hour 3 to 8): Dominion parser first (the easier one)

File: `pipeline/parse_desc.py`

Each `N.txt` is one project and always follows this order:

```
Project 43 of 44
Dominion Energy South Carolina
Planned Transmission Projects $2M and above Total
5 Year Budget
<PROJECT NAME>
Project ID
<ID>
Project Description
<description, may wrap across lines>
Project Need
...
Project Status
<status>
Planned In-Service Date
<date>
Estimated Project Cost
Previous 2024 2025 2026 2027 2028 Total*
$... $... $... $... $... $... $<TOTAL>
```

Extract by finding each label line and taking the text that follows it.

**Watch out for:**
* Dates come in two formats: `12/31/2027` and `06/01/24`. Normalize to `2027-12-31` and `2024-06-01`.
* Endpoint separators vary: `–` (long dash), `-`, and ` - `. Split on all of them.
* Names may have extras like `/ LR Plumb Branch 46 kV Rebuilds`. Keep the full `project_name`, but set `endpoint_a` and `endpoint_b` from the first two substation names.
* Length appears in the description as text like `4.5 miles.` Use a regex like `(\d+(\.\d+)?)\s*miles?`.
* Cost: take the last dollar amount on the cost row (the Total).

**Done when:** 44 rows, no blank `in_service_date`, and you spot checked 5 rows against the original text.

### Block 3 (Hour 8 to 12): Georgia Power parser

File: `pipeline/parse_gpc.py`

The file has a summary table and **208 detail blocks**. Use the detail blocks. Each looks like:

```
SAV: MCINTOSH - PURRYSBURG 230KV REACTORS
Teams # 20277
Need Date 06/01/2026 Start Date 01/01/2024
Description
...
```

Find every line starting with `Teams # `. The line **directly above** is the project name, and the line **directly below** has both dates.

**Watch out for:**
* Typos in the source, like `23O KV` (letter O instead of zero). Replace `O` with `0` when it sits between digits and `KV`.
* Voltage appears as `230KV`, `230 KV`, or `230-115KV`. Take the highest number.
* Some names contain `(SAV)` or other notes in parentheses. Strip those out of the endpoint names, but keep them in `project_name`.
* Many GPC projects are relay or equipment upgrades at a single substation (for example `SCOTTDALE RELAY MODERNIZATION`). Keep them, but set `project_type = relay` and leave `endpoint_b` blank.
* Every page repeats a long CEII disclaimer paragraph. Ignore any line that is part of that boilerplate.

**Done when:** 208 rows (or a count you can explain), then CP2.

### Block 4 (Hour 12 to 14): Merge and classify

File: `pipeline/build_raw.py`

Combine both parsers into `data/interim/projects_raw.csv`. Fill `project_type` using keywords in the name:

| If the name contains | `project_type` |
| --- | --- |
| `CONSTRUCT`, `NEW`, `#2` (a second line) | `new_line` |
| `REBUILD` | `rebuild` |
| `RECONDUCTOR` | `reconductor` |
| `RELAY`, `MODERNIZATION`, `PANEL` | `relay` |
| `TRANSFORMER`, `REACTOR`, `STATCOM`, `SUB` only | `substation` |
| anything else | `other` |

Write a quick sanity report and post it in chat: rows per utility, rows per `project_type`, how many have a `voltage_kv`, and the date range.

### Block 5 (Hour 14 to 24): Human verification

After Anders G runs the geocoder, they will send you the `low` and `unmatched` projects. For each one:

1. Reread the source text for clues (county, nearby town, landmarks)
2. Look up the substation on [Open Infrastructure Map](https://openinframap.org) or OpenStreetMap
3. If you find it, send the correct coordinates to David P's `PATCH /projects/{id}` endpoint (or a shared sheet if the endpoint is not ready), with `human_verified: true`
4. If you cannot confirm it, leave it as low confidence. **Do not guess.** A wrong location creates a fake overlap.

**Prioritize projects near the SC and GA border** (Augusta, Aiken, Savannah, Hilton Head, Beaufort areas). That is where real overlaps live. A project in Atlanta will never be within 25 miles of a Dominion project, so it is not worth your time.

### Block 6 (Hour 24 onward): Support the demo

* Pick 2 or 3 overlaps with the strongest story, and write one sentence each on why they matter
* Be ready to answer judges' data questions: "How many projects did you parse? How did you handle bad matches?"

## Phase 2 preview (only after CP3)

You will own the **Street View Verifier's review queue**. You'll show the imagery for each medium confidence match and record whether a substation is visible.

## Your definition of done

* [ ] `projects_raw.csv` has 252 rows (44 DESC + 208 GPC) or an explained count
* [ ] Zero rows break the contract (right columns, ISO dates, integer kV)
* [ ] Every border area project with low confidence has been reviewed by hand
