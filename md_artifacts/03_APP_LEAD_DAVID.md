# David P: App Lead

**Your mission:** Build what the judges see and touch: the API, the interactive map, the ranked list, and the cost brief panel. You also own the demo and pitch. Since you'll never have to wait for real data, your first job is to make the whole app work on **fixture data**.

Read `00_TEAM_CONTRACT.md` first. The API endpoints you build are defined there.

## You hand off to

* **Everyone:** at CP1, a running app anyone can open at `http://localhost:5173`
* **Luis D:** the `PATCH /projects/{id}` endpoint they use to save manual location fixes

## You receive from

* **Anders G:** `data/processed/projects.csv`, `overlaps.csv`, and `briefs.csv`. Your loader must work on these the moment they appear.

## Background you need

* Each project is a line between two substations, or a single point. Draw it as a line when both endpoints exist and as a dot otherwise.
* Two projects **overlap** when their center points are under 25 miles apart. The challenge requires the overlaps to be **visually highlighted** and the map to be **interactive** (pan, zoom, click). A static image fails the requirement.
* **Confidence** says how sure we are about a location. Showing it honestly is a feature, not a weakness.

## Task list

### Block 1 (Hour 0 to 3): Fixtures, skeleton, CP1

**1. Create the repo** with the folder layout from the contract. Add `.gitignore` with `gridlock.db`, `.env`, `node_modules/`, and `__pycache__/`.

**2. Build fixtures** (`api/make_fixtures.py`). Read the starter spreadsheet's `projects` and `overlaps` sheets with `openpyxl` or `pandas`, and write `data/fixtures/projects.csv` and `overlaps.csv` using the **contract's column names**:
* `utility`: map `Georgia Power` to `GPC` and `Dominion Energy South Carolina` to `DESC`
* `endpoint_a` / `endpoint_b` from `name_a` / `name_b`
* Dates to ISO. Two are Excel serial numbers: `45809` is `2025-06-01` and `45778` is `2025-05-01`
* Set `confidence = 1.0` and `confidence_tier = high` for all fixture rows
* Fill missing columns with blanks

Post in chat when fixtures exist. Anders G needs them for testing.

**3. Database loader** (`api/load_db.py`). Load CSVs into SQLite tables `projects`, `overlaps`, and `briefs`. Take a flag: `--source fixtures` or `--source processed`. This one flag is how we swap from fake to real data with zero code changes.

**4. FastAPI server** (`api/main.py`). Implement the `GET` endpoints from the contract. Enable CORS for `http://localhost:5173`. Run with `uvicorn api.main:app --reload`.

**5. Map skeleton** (`web/`). Use `npm create vite@latest web -- --template react`, then `npm i leaflet react-leaflet`. Show the 10 fixture projects on a map centered around Augusta and Savannah (roughly lat 33.0, lon -81.5, zoom 7).

**CP1 is yours to call.** When the map shows fixture data from the API, post a screenshot.

### Block 2 (Hour 3 to 12): The map that wins

Build these in order:

1. **Two utilities, two colors.** For example, GPC in blue and DESC in orange, plus a legend. Lines for two endpoint projects, circle markers for one endpoint projects.
2. **Confidence styling.** High = solid line or filled marker. Medium = dashed line. Low = hollow marker at 50% opacity. Put it in the legend.
3. **Overlap highlighting.** For each overlap, draw a thin connecting line between the two center points, colored by score (for example, red for the strongest). When an overlap is selected, draw a 25 mile circle around each center: `L.circle(center, { radius: 40234 })` (25 miles in meters).
4. **Ranked sidebar.** Show the list from `GET /overlaps`: rank, both project names, distance, time gap, score. Clicking a row flies the map to that pair (`map.flyToBounds`) and opens its detail panel.
5. **Click a project** for a popup with name, utility, voltage, in service date, confidence tier, and source reference.
6. **Time slider.** A year range from 2024 to 2034. Only show projects (and overlaps) whose in service date falls in the window. It's a small feature, but it demos really well.

### Block 3 (Hour 12 to 20): Switch to real data (CP2 and CP3)

* As soon as Anders G pushes processed CSVs, run `load_db.py --source processed` and check that everything still renders
* Expect about 250 projects. If the map gets cluttered, add a toggle for "show only projects involved in an overlap"
* Build `PATCH /projects/{project_id}` for Luis D's manual fixes. It should update the database and also append the fix to `data/processed/manual_fixes.csv`, so Anders G can fold it back into the next pipeline run

### Block 4 (Hour 20 to 28): Cost brief panel (bonus points)

When an overlap is selected, show a detail panel with:
* Both projects side by side (name, dates, voltage, length, cost if known)
* **Two sliders:** shared corridor miles (0 to 10) and land cost per acre ($2,000 to $50,000). Each change calls `GET /briefs/{id}?shared_mi=...&cost_per_acre=...` and updates the savings number live
* The `assumptions_note`, shown clearly, labeled "Assumptions"
* A **"Generate summary"** button that calls `POST /briefs/{id}/narrative`

The narrative endpoint sends the overlap and brief data to the Claude API (`anthropic` Python SDK, key from `.env`). A good starting prompt:

```
You are writing for utility planners. In 3 to 4 sentences, explain why these two
planned projects are a coordination opportunity. Use only the data provided.
State savings as rough estimates and mention the key assumption.
DATA: <overlap + both projects + brief as JSON>
```

Cache the result in the `briefs` table so the demo doesn't depend on a live API call. **Pregenerate narratives for the top 3 before demo time.**

**CP4 (Hour 28): feature freeze.** After this, only bug fixes and demo polish.

### Block 5 (Hour 28 onward): Demo and pitch

You drive the demo. Draft the script with your teammates and rehearse it at least twice.

**Suggested 3 minute flow:**
1. **The problem (30 sec):** Neighboring utilities plan construction in isolation. FERC Order 1920 (2024) exists because of this.
2. **The data (30 sec):** We parsed 252 real projects from Georgia Power's and Dominion's public filings, geocoded them with OpenStreetMap, and scored our confidence in every location.
3. **Live demo (90 sec):** Zoom to the Savannah River border, click the #1 overlap, show both 25 mile circles, drag the time slider, open the cost brief, move a slider.
4. **Why it's trustworthy (15 sec):** Show the confidence legend and explain how low confidence matches were checked by hand.
5. **What's next (15 sec):** Street View verification and shared crew routing (our Phase 2).

**Backup plan:** record a screen capture of the full demo at CP4. If WiFi or anything else fails on stage, play the video.

## Phase 2 preview (only after CP3)

You will add a **Street View panel** to the project popup and a **route line** for the shared crew path to the overlap detail view.

## Your definition of done

* [ ] App runs from a clean clone with the README steps
* [ ] Map shows both utilities, confidence styling, and highlighted overlaps
* [ ] Ranked sidebar is clickable and flies to each pair
* [ ] Cost brief panel with live sliders works for the top 3 overlaps
* [ ] Demo rehearsed twice, backup video recorded
