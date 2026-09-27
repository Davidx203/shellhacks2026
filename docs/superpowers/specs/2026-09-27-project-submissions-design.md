# Project submissions (PDF upload and manual form): design

Status: draft for review. Date: 2026-09-27.

## Goal

Let a utility add or update a planned project without anyone editing CSVs. A submission is either a PDF in one of our two existing layouts or a manual form. Both produce the same row that `projects_raw.csv` holds today, so the existing geocode, route, overlap and rank steps process it with no special cases. A new or updated project appears on the map and, if it is near another utility's project, in the ranked overlaps.

## Decisions already made

| Topic | Decision |
| --- | --- |
| Review | Live immediately, flagged `submitted`, confidence capped until verified, reversible (reject and restore) |
| Identity | Company dropdown (Georgia Power or Dominion), no login |
| PDFs | Only our two existing layouts, one or many projects per file, confirmed in a table before saving |
| Duplicates | Same utility project ID updates the existing project; old values are kept in history |
| Location | Endpoint names, plus optional coordinates per endpoint that override name matching |
| Architecture | Submissions are another input to the existing pipeline (approach A) |

## Out of scope

- Logins, roles, emails or notifications.
- Utilities other than GPC and DESC (the contract allows only these two).
- Editing cells inside the confirmation table. A wrong PDF row is corrected by submitting the manual form for that project ID.
- Reading PDFs in any layout other than the two we already parse.
- Dropping pins on a map to set a location.

## Architecture

```
PDF or form  ->  API preview (parse, validate, diff)  ->  submitter confirms
                                    |
                              API commit
                                    v
                data/interim/submissions.csv   (append-only revisions, the history)
                                    |
                build_raw.py  merges report rows + latest active submissions
                                    v
                data/interim/projects_raw.csv
                                    |
   geo/run_all.py (unchanged flow) -> data/processed/*.csv -> load_db -> gridlock.db -> API -> map
```

`build_raw.py` merges onto a committed baseline, `data/interim/projects_report.csv`, rather than re-parsing the report text. The extracted report text is gitignored, so a machine without it (for example the app lead's) could not rebuild otherwise. When the text is present, `build_raw.py` re-parses it and refreshes the baseline.

The rebuild (`build_raw.py`, then `geo/run_all.py`, then the database load) runs as a background job started by the commit call. It takes about 10 seconds with caches, plus about 1 second per new place name that needs a Nominatim lookup.

## Components

### 1. `pipeline/pdf_submission.py` (PDF reader)

- `read_pdf(bytes, utility) -> list[dict]` returns contract rows (`parse_gpc.parse_text` or `parse_desc.parse_page` output).
- Extracts text with PyMuPDF. Detects the layout: `Teams # ` lines mean the Georgia Power layout; pages containing `Project ID` and `Planned In-Service Date` mean the Dominion layout (one project per page).
- Errors, each with a plain message: not a PDF (magic bytes), too large (over 20 MB), too many pages (over 800), no text layer, layout not recognised, layout does not match the selected company.
- `source_file` is `submission:<filename>` and `source_ref` comes from the parser, so anyone can trace a row to its origin. The original PDF is kept at `data/submissions/<submission_id>.pdf` (gitignored).

### 2. `pipeline/submission_store.py` (validation, diff, storage)

- `normalize_form(payload) -> dict`: builds a contract row from the manual form. Derives `state` from the utility, `project_type` with the existing `classify`, and `endpoint_a/b` from the names (or from the project name with the existing `endpoints()` when the form leaves them blank). `build_start` is the given start, else 1 January of the in-service year (the same fallback the Dominion parser uses); `build_end` is the in-service date. If no utility project ID is given it generates `GPC_SUB1`, `GPC_SUB2`, and so on (`DESC_SUB1`...).
- `validate(row) -> list[str]`: reuses `pipeline/validate.py` rules, plus: project name required, in-service date required, at least one endpoint, kV integer, dates ISO, `build_start <= build_end`, coordinates in the GA/SC bounding box and supplied as pairs.
- `diff(row, existing_rows) -> {status, changes}`: `new`, `update` (with `{field: [old, new]}`), `unchanged`, or `invalid`. "Existing" means the current merged row, so a resubmission of an identical row is `unchanged`. `unchanged` rows are shown but cannot be committed, since they would only add an empty revision.
- `append(rows, origin, utility, submitted_by) -> submission_ids`, `set_status(submission_id, "rejected" | "active")`, `list_history()`. All writes hold a file lock and write atomically (temp file then rename). A status change rewrites the small file under the lock; rows are never deleted, so the history is complete.

**`submissions.csv` columns:** every `projects_raw.csv` contract column, plus `submission_id`, `origin` (`pdf` or `form`), `submitted_by` (the company plus optional free text), `submitted_at` (UTC ISO), `status` (`active` or `rejected`), `given_lat_a`, `given_lon_a`, `given_lat_b`, `given_lon_b`.

**Merge rule** (in `build_raw.py`): report rows are read as today. For each `project_id`, the latest active submission wins; its non-blank fields override the report row, blank fields keep the existing value (so a field cannot be cleared through a submission; that is a manual edit). New IDs are appended. Rejecting a submission removes it from the merge, so the report values (or the earlier submission) return.

### 3. Pipeline changes

- `projects_raw.csv` gains `origin` (`report` or the submission origin), `submission_id`, `submitted_by`, `submitted_at`, and `given_lat_a/lon_a/lat_b/lon_b`. The contract's `COLUMNS` stays as the 16 core columns; a new `RAW_COLUMNS` adds the extras, and `validate.py` and the contract test are updated.
- `geo/geocode.py`: when `given_lat_*` is present for an endpoint, that endpoint is taken as located at those coordinates, method `submitted_coordinates`, and name matching is skipped for it.
- `geo/run_all.py`: after scoring, projects with `origin != "report"` and `human_verified != "true"` have confidence capped at `SUBMISSION_CEILING = 0.6` (tier `medium` at best). A hand verification in `manual_fixes.csv` still lifts it to `high` as today.
- `api/load_db.py`: writes to `gridlock.db.tmp` and swaps it in with `os.replace`, so the API never reads half-loaded tables during a rebuild.

### 4. API (`api/submissions.py`, mounted in `api/main.py`)

| Method and path | Purpose |
| --- | --- |
| `POST /submissions/preview/pdf` | Multipart: `utility`, `file`. Returns rows with `status`, `changes`, `errors`. Nothing is saved. |
| `POST /submissions/preview/form` | JSON form payload. Same response shape. |
| `POST /submissions/commit` | JSON: `utility`, `origin`, `submitted_by`, `rows`. The server re-validates and re-diffs, never trusting the client's status. Only valid rows are saved. Returns `submission_ids` and a `job_id`. |
| `GET /submissions/jobs/{job_id}` | `queued`, `running`, `done`, `failed`, with a message. |
| `GET /submissions` | History, newest first, including rejected. |
| `POST /submissions/{id}/reject` and `/restore` | Reversible. Both start a rebuild job. |
| `POST /submissions/rebuild` | Manual retry after a failed rebuild. |

The rebuild runs in a single background worker. A request that arrives while a rebuild is running marks it dirty, and it runs once more afterwards, so two commits in a row never race. The build and run steps run as subprocesses (`python -m pipeline.build_raw`, then `python geo/run_all.py`) followed by the database load.

### 5. Frontend (`web/`)

- A "Submit a project" button in the header opens a dialog with two tabs, **Upload PDF** and **Manual form**, and a **History** tab.
- The upload tab has a company dropdown and a file chooser. The preview is a table with a New / Update / Unchanged / Invalid badge, changed fields listed for updates, per-row errors, and a checkbox per row. **Confirm** commits the checked rows.
- The manual tab has: company (dropdown), utility project ID (optional), project name, endpoint A, endpoint B (optional), voltage kV, length, estimated cost, build start (optional), in-service date, optional coordinates for each endpoint, and submitted-by text. It previews before saving, like the PDF tab.
- After commit the dialog shows the rebuild job's progress, then reloads the map data and links to the new project.
- The History tab lists submissions with Reject and Restore buttons.
- Submitted projects show a **Submitted** badge in the popup and a dashed line on the map.

## Data flow for one submission

1. The user picks a company and uploads a PDF or fills the form.
2. The server parses and validates, compares against the current merged data, and returns the preview. Nothing is stored.
3. The user confirms the rows to add. The server re-validates, appends rows to `submissions.csv` and starts the rebuild job.
4. `build_raw.py` merges, `run_all.py` geocodes, routes, scores and ranks, and the database is swapped in.
5. The map reloads and shows the new or changed project. Its confidence is capped and it carries the Submitted badge until someone verifies it.

## Error handling

- **Bad upload:** the plain-language messages above, returned as HTTP 422 (413 for size). The dialog shows them inline.
- **Invalid rows:** shown in the preview with per-row errors; they cannot be checked for commit.
- **Rebuild failure:** the job ends `failed` with the error text; `submissions.csv` still holds the rows, the old database keeps serving, and `POST /submissions/rebuild` retries.
- **No network during rebuild:** endpoint inference already degrades gracefully (cached data and offline place lookup); the run finishes with fewer inferred endpoints.
- **Two writers:** the file lock and the single rebuild worker prevent lost updates.

## Testing

- **PDF reader:** build small PDFs in the tests with PyMuPDF from real snippets of each layout; check both layouts parse, a mismatched company is rejected, and empty, non-PDF and oversized inputs give the right errors. Add a test on the real Dominion PDF (44 rows) and a sample of the Georgia Power PDF.
- **Store:** normalization, validation rules, `new`/`update`/`unchanged` diffs, the merge rule (override, blank keeps existing, reject restores the report value), atomic append and status changes under concurrent calls.
- **Pipeline:** `build_raw` merge with a submissions file; `given_lat_*` skips name matching; the confidence cap for unverified submissions and the lift from `manual_fixes.csv`; the updated contract test.
- **API:** every endpoint through `TestClient`, including the rebuild job lifecycle with the subprocess stubbed, plus one end-to-end test that runs a real rebuild on a small fixture and checks the new project appears in `/projects`.
- **Frontend:** the dialog logic checked with the same stubbed-map approach used so far; manual browser pass with a real Mapbox token before merging.

## Contract updates

`md_artifacts/00_TEAM_CONTRACT.md` documents: `submissions.csv`, the extra `projects_raw.csv` columns, the new endpoints, and the confidence cap. David and Anders need to agree before merge.

## Open items

None blocking. Two choices I made that you can change: uploads are limited to 20 MB and 800 pages (the Georgia Power report is 668 pages), and the confidence cap for unverified submissions is 0.6.
