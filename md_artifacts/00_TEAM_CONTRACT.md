# Gridlock Radar: Team Contract (Phase 1 MVP)

**Everyone reads this file first.** It defines the handoffs between the three of us: file names, column names, API endpoints, and who owns what. If we all build to this contract, our pieces snap together without anyone waiting on anyone else.

**Rule:** Nobody changes this contract alone. If something needs to change, say so in the team chat, get a thumbs up from both teammates, update this file, and commit it on its own.

## The goal of Phase 1

Meet every Sperry Tech Gridlock requirement, including the bonus:

1. An interactive map showing both utilities' planned projects, with overlaps highlighted
2. A ranked list of the top coordination opportunities
3. **Bonus:** a rough cost or impact estimate for at least one overlap

Waymo features (Street View verification, shared crew routing) are **Phase 2**. Nobody starts Phase 2 work until Checkpoint 3 is hit.

## Who owns what

| Role | Owns | Folder |
| --- | --- | --- |
| **Luis D: Data Lead** | Turning both utility reports into clean project tables. Manual review of low confidence matches. | `pipeline/` |
| **Anders G: Geo Lead** | Coordinates, confidence scores, overlap math, ranking, cost estimate numbers. | `geo/` |
| **David P: App Lead** | FastAPI server, database loading, web app map and sidebar, Claude narratives, demo and pitch. | `api/`, `web/` |

**Only edit files in your own folder.** Shared files (`data/processed/`, this contract) have a single writer, listed below.

## Good news about the source data

Both "PDFs" in the project files are **already extracted text**, so we do not need OCR.

* **Georgia Power** (`2025_IRP_Volume_3_PUBLIC_DISCLOSURE.pdf`) is a plain text file. It has 208 project detail blocks, each starting with a title line followed by `Teams # <id>` and a `Need Date` / `Start Date` line. Costs are redacted.
* **Dominion Energy SC** (`2024-2028-2million-and-above-project-descriptions.pdf`) is a zip archive. Inside are 44 page images plus 44 matching `.txt` files, one project per page, with a name, project ID, description (often including line length in miles), in service date, and **estimated cost**.

## Repo layout

```
gridlock/
  data/
    raw/            # original files, never edited
      gpc_irp_vol3.txt
      desc_pages/   # unzipped 1.txt to 44.txt (+ jpegs)
      starter_projects_overlaps.xlsx
    interim/        # Luis D writes here
      projects_raw.csv
    processed/      # Anders G writes here
      projects.csv
      overlaps.csv
      briefs.csv
    fixtures/       # David P creates on day one from the starter sheet
      projects.csv
      overlaps.csv
  pipeline/         # Luis D
  geo/              # Anders G
  api/              # David P
  web/              # David P
  gridlock.db       # built by api/load_db.py, never committed
```

## Data contract

All dates are ISO format `YYYY-MM-DD`. All distances are miles. All coordinates are decimal degrees (WGS84, same as Google Maps).

### `data/interim/projects_raw.csv` (written by Luis D)

| Column | Type | Example | Notes |
| --- | --- | --- | --- |
| `project_id` | string | `GPC_20277`, `DESC_6810O` | Utility prefix + the utility's own ID, spaces removed |
| `utility` | string | `GPC` or `DESC` | Only these two values |
| `state` | string | `GA` or `SC` | |
| `project_name` | string | `SAV: MCINTOSH - PURRYSBURG 230KV REACTORS` | Exactly as written in the source |
| `endpoint_a` | string | `MCINTOSH` | First substation name, cleaned |
| `endpoint_b` | string | `PURRYSBURG` | Second substation name, blank if the project is at one site |
| `voltage_kv` | integer | `230` | Highest voltage mentioned. Blank if none |
| `project_type` | string | `rebuild` | One of `new_line`, `rebuild`, `reconductor`, `substation`, `relay`, `other` |
| `length_mi` | float | `4.5` | Only if the source states it. Blank otherwise |
| `est_cost_usd` | integer | `3000000` | DESC only (GPC costs are redacted). Blank otherwise |
| `start_date` | date | `2024-01-01` | Blank if not given |
| `in_service_date` | date | `2026-06-01` | GPC calls this "Need Date" |
| `build_start` | date | `2024-01-01` | Start of the build window. GPC: its `Start Date`. DESC: Jan 1 of the first budget year with spend (`Previous` spend counts as `2023-01-01`), since DESC gives no start date. Never after `build_end` |
| `build_end` | date | `2026-06-01` | Same as `in_service_date` |
| `source_file` | string | `desc_pages/43.txt` | So anyone can check the original |
| `source_ref` | string | `Project 43 of 44` or `Teams # 20277` | |

### `data/processed/projects.csv` (written by Anders G)

Every column from `projects_raw.csv`, plus:

| Column | Type | Notes |
| --- | --- | --- |
| `lat_a`, `lon_a` | float | Location of endpoint A. Blank if not found |
| `lat_b`, `lon_b` | float | Location of endpoint B. Blank if not found |
| `lat_center`, `lon_center` | float | Midpoint of A and B. If only one is found, that point |
| `osm_id_a`, `osm_id_b` | string | OpenStreetMap feature IDs, for traceability |
| `confidence` | float | 0.0 to 1.0 |
| `confidence_tier` | string | `high` (0.8 and up), `medium` (0.5 to 0.8), `low` (below 0.5), `unmatched` |
| `human_verified` | boolean | `true` once Luis D confirms it against the source |
| `route_mi` | float | Length of the route found along same-voltage OSM power lines between endpoint A and B. Blank if no route. Geometry is in `routes.geojson` |

### `data/processed/overlaps.csv` (written by Anders G)

| Column | Type | Notes |
| --- | --- | --- |
| `overlap_id` | string | `OVL_1`, `OVL_2`, ... in rank order |
| `project_id_gpc` | string | |
| `project_id_desc` | string | |
| `distance_mi` | float | **Closest-point** distance between the two projects' geometries (route, else the A-B segment, else the point), 2 decimals |
| `band` | string | `crossing` (touching, <=0.05 mi), `share_land` (<1 mi, about 1.6 km), `share_logistics` (<5 mi, about 8 km), `share_crews` (<25 mi, about 40 km) |
| `time_gap_days` | integer | Absolute difference between in service dates |
| `windows_overlap` | boolean | Build windows (`build_start` to `build_end`) intersect |
| `overlap_days` | integer | Days the two build windows overlap (0 if they do not) |
| `window_gap_days` | integer | Days between the windows when they do not overlap (0 if they overlap) |
| `voltage_match` | boolean | Same `voltage_kv` on both |
| `score` | float | 0.0 to 1.0, see formula in `02_GEO_LEAD_ANDERS.md` |
| `rank` | integer | 1 is the best opportunity |

Only pairs under 25 miles apart get a row.

### `data/processed/briefs.csv` (written by Anders G, narrative added by David P)

| Column | Type | Notes |
| --- | --- | --- |
| `overlap_id` | string | |
| `shared_corridor_mi` | float | Assumption, adjustable in the UI |
| `row_width_ft` | integer | Assumption based on voltage |
| `shared_acres` | float | |
| `land_cost_per_acre_usd` | integer | Assumption, adjustable in the UI |
| `est_land_savings_usd` | integer | |
| `assumptions_note` | string | Plain English list of every assumption used |

## API contract (built by David P, used by the web app)

Base URL during development: `http://localhost:8000`

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/projects?utility=GPC&min_confidence=0.5` | List of projects. Both filters optional |
| `GET` | `/overlaps?limit=20` | Ranked overlaps, each with both projects nested inside |
| `GET` | `/overlaps/{overlap_id}` | One overlap with both projects and its brief |
| `GET` | `/briefs/{overlap_id}?shared_mi=5&cost_per_acre=10000` | Brief recalculated with the slider values |
| `POST` | `/briefs/{overlap_id}/narrative` | Calls Claude, returns a plain English summary |
| `PATCH` | `/projects/{project_id}` | Manual fix: body `{lat_center, lon_center, human_verified}` |

Example `GET /overlaps` response item:

```json
{
  "overlap_id": "OVL_1",
  "rank": 1,
  "score": 0.87,
  "distance_mi": 5.65,
  "time_gap_days": 152,
  "voltage_match": true,
  "gpc": { "project_id": "GPC_20277", "project_name": "...", "lat_center": 32.35, "lon_center": -81.18, "in_service_date": "2026-06-01", "confidence_tier": "high" },
  "desc": { "project_id": "DESC_XXXX", "project_name": "...", "lat_center": 32.35, "lon_center": -81.08, "in_service_date": "2025-12-31", "confidence_tier": "medium" }
}
```

## Submissions (companies add or update projects)

A company can upload a PDF (Georgia Power IRP layout or Dominion project page layout) or fill a form. Submissions live in `data/interim/submissions.csv` (append-only revisions, gitignored runtime state). `pipeline/build_raw.py` lays the latest active submission per `project_id` over `data/interim/projects_report.csv` (the committed baseline of parsed report rows) to write `projects_raw.csv`.

**New `projects_raw.csv` columns** (after the 16 contract columns): `origin` (`report`, `pdf` or `form`), `submission_id`, `submitted_by`, `submitted_at`, `given_lat_a`, `given_lon_a`, `given_lat_b`, `given_lon_b` (optional coordinates that skip name matching for that endpoint). These flow through to `projects.csv`.

**Rules:** blank submitted fields keep the existing value (a form update derives and defaults nothing, so it changes only what was filled in); the current state is the baseline plus active submissions, not the last rebuild's output; generated ids (`GPC_SUB1`, ...) are never reused, even after a reject; the original PDF is kept at `data/submissions/<sha256>.pdf` and every row it produced carries `[pdf sha256:<16>]` in `source_ref`; only valid, changed rows are saved; unverified submissions are capped at confidence 0.6 (`medium`) until `manual_fixes.csv` verifies them; rejecting a submission restores the previous values.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/submissions/preview/pdf` | multipart `utility`, `file`; returns `upload_sha256` and rows with `status` (`new`, `update`, `unchanged`, `invalid`), `changes`, `errors`, and a `summary` (the project as it will read after the update) |
| `POST` | `/submissions/preview/form` | JSON form fields; same response |
| `POST` | `/submissions/commit` | `{utility, origin, submitted_by, rows, expected, upload_sha256}`; `expected` maps project id to the status the submitter saw in the preview (a row whose status changed since is skipped); diff and save happen in one locked step, so a repeat saves nothing; returns `saved`, `skipped`, `job_id` |
| `GET` | `/submissions/jobs/{job_id}` | `queued`, `running`, `done`, `failed` with a message |
| `GET` | `/submissions` | history, newest first |
| `POST` | `/submissions/{id}/reject` and `/restore` | reversible; each starts a rebuild |
| `POST` | `/submissions/rebuild` | retry after a failed rebuild |

A rebuild runs `python -m pipeline.build_raw`, `python geo/run_all.py`, then `python api/load_db.py --source processed` from `gridlock/`. `run_all.py` needs the cached OSM data; without the power-line cache it skips routes and endpoint inference and says so.

## Checkpoints

Times are hours after we start coding. Adjust to the real schedule, but keep the order.

| Checkpoint | When | Done means |
| --- | --- | --- |
| **CP1: Skeleton** | Hour 3 | Repo created, folders exist, fixtures built from the starter sheet, API serves fixtures, map shows 10 starter projects |
| **CP2: First real data** | Hour 12 | GPC fully parsed, overlap engine matches the starter sheet's distances, map reads from the real API |
| **CP3: Full pipeline** | Hour 20 | Both utilities parsed and geocoded, real overlaps ranked and on the map. **Phase 1 is submittable from here.** |
| **CP4: Feature freeze** | Hour 28 | Cost briefs, time slider, confidence styling done. Only bug fixes after this |
| **Demo rehearsal** | Hour 32 | Full run through of the pitch at least twice |

At each checkpoint, we all stop for 10 minutes, merge to `main`, run the app end to end, and confirm the next block's plan.

## Git workflow

* Branches: `data/<thing>`, `geo/<thing>`, `app/<thing>`
* Small commits, merge to `main` at least every 2 hours and at every checkpoint
* Never commit `gridlock.db`, API keys, or `.env` files
* Keys live in `.env` (`ANTHROPIC_API_KEY=...`). Share them privately, never in chat screenshots

## Status updates

Post in the team chat every 2 hours in this format:

```
Done: GPC parser handles 208 of 208 blocks
Next: voltage + project_type extraction
Blocked: nothing / need X from Anders G
```

If you are blocked for more than 20 minutes, say so immediately. Do not sit on it.

## Stack

* Python 3.11+: `pandas`, `rapidfuzz`, `requests`, `fastapi`, `uvicorn`, `anthropic`, `openpyxl`
* Web: Vite + React + `react-leaflet` (plain HTML + Leaflet is fine if faster for David P)
* Database: SQLite
