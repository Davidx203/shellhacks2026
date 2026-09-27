# Project Submissions (PDF upload and manual form) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a utility add or update planned projects by uploading a PDF in one of our two report layouts or by filling a form; both flow through the existing pipeline into the database and onto the map.

**Architecture:** Submissions are an append-only CSV (`data/interim/submissions.csv`) that `build_raw.py` merges on top of a committed baseline of parsed report rows into `projects_raw.csv`. A background worker then runs `build_raw`, `geo/run_all.py` and `api/load_db.py`. A FastAPI router previews (parse, validate, diff) and commits; a dialog in the web app drives it.

**Tech Stack:** Python 3.13, FastAPI (`python-multipart` for uploads), PyMuPDF, pytest, plain HTML/JS with Mapbox GL, `node --test` for JS helpers.

**Spec:** `docs/superpowers/specs/2026-09-27-project-submissions-design.md` (read it first; it holds the decisions and the reasons).

**Branch:** create `luis/project-submissions` from `main` before Task 1 (`git checkout -b luis/project-submissions`).

**Running things:** every command runs from the repo root `/Users/luisdelgado/Desktop/shellhacks2026` with `venv/bin/python`. The `pipeline` package lives under `gridlock/`, so run it as a module with `PYTHONPATH=gridlock venv/bin/python -m pipeline.build_raw`; run the geocoder as a script with `venv/bin/python gridlock/geo/run_all.py`. pytest needs neither (it adds `gridlock/` to the path itself).

## Global Constraints

- Companies are only `GPC` (Georgia Power, state `GA`) and `DESC` (Dominion Energy SC, state `SC`). No logins; the company is a dropdown.
- Upload limits: 20 MB and 800 pages (`MAX_BYTES = 20 * 1024 * 1024`, `MAX_PAGES = 800`).
- PDFs: only the two existing layouts (Georgia Power `Teams # ` blocks; Dominion one project per page with `Project ID` and `Planned In-Service Date`). No LLM extraction.
- Dates are ISO `YYYY-MM-DD`. Distances are miles. Coordinates are decimal degrees, latitude first, longitude negative in GA/SC.
- Generated project IDs are `GPC_SUB1`, `GPC_SUB2`, ... and `DESC_SUB1`, ...; user-supplied IDs have spaces removed and get the `GPC_` or `DESC_` prefix.
- Update rule: for an existing `project_id`, the latest active submission wins; non-blank submitted fields override, blank fields keep the existing value. A field cannot be cleared through a submission.
- `unchanged` rows are shown in the preview but cannot be committed. Only valid rows are saved. The server re-validates and re-diffs on commit and never trusts client-supplied status.
- Unverified submitted projects (`origin != "report"` and `human_verified != "true"`) have confidence capped at `SUBMISSION_CEILING = 0.6`. A hand verification in `manual_fixes.csv` still lifts them to `high`.
- Rejecting a submission is reversible (`status` `rejected` and back to `active`); rows are never deleted.
- All writes to `submissions.csv` hold a file lock and are atomic (temp file in the same directory, then `os.replace`). The database is swapped in atomically (`gridlock.db.tmp` then `os.replace`).
- Only edit inside `gridlock/`, `docs/superpowers/`, `md_artifacts/00_TEAM_CONTRACT.md` and `.gitignore`.

## Review Focus

These are inputs the spec implies but that are easy to overlook. Each has a test in the task named in brackets.

1. **Wrong or damaged upload:** a non-PDF renamed `.pdf`, a corrupt PDF, a scanned PDF with no text, a PDF whose layout we do not read, or the wrong company selected. Expect a specific plain message and HTTP 422 (413 for size), never a 500. [Task 2, Task 7]
2. **Values as people type them:** `$3,000,000`, `230 kV`, `06/01/2026`, trailing spaces, lower-case `gpc`, a real-looking but impossible date like `13/45/2026`. Expect either normalization to the contract form or a specific error naming the field; never a silently dropped value. [Task 3]
3. **Bad coordinates:** latitude and longitude swapped, outside Georgia and South Carolina, only one of the pair, or given for an endpoint with no name. Expect a rejection that says what is wrong. [Task 3]
4. **Double submit and races:** clicking Confirm twice, two people committing at once, the same project ID twice in one PDF. Expect no lost update, no duplicate revision, and a clear "duplicate" or "unchanged" message. [Task 3, Task 7]
5. **Rebuild fails or is slow** (no network, missing cache, a crash): the job ends `failed` with the error text, the old database keeps serving, submissions are kept, and a retry works. [Task 6, Task 7]

Also covered: unsafe characters in an ID (they end up in URLs), spreadsheet-formula prefixes (`=`, `+`, `@`) in text fields, over-long names, and a client that forges `status` or `submission_id` in a commit body.

## File Structure

| File | Responsibility |
| --- | --- |
| `gridlock/pipeline/common.py` (modify) | `RAW_EXTRA`, `RAW_COLUMNS` |
| `gridlock/pipeline/classify.py` (modify) | `finalize_row` (project type, relay rule) |
| `gridlock/pipeline/pdf_submission.py` (create) | Read an uploaded PDF into contract rows; `SubmissionError` |
| `gridlock/pipeline/submission_store.py` (create) | Form normalization, validation, diff, merge, locked append-only log |
| `gridlock/pipeline/build_raw.py` (modify) | Baseline + submissions merge |
| `gridlock/pipeline/validate.py` (modify) | Check against `RAW_COLUMNS` |
| `gridlock/geo/geocode.py` (modify) | Given coordinates skip name matching |
| `gridlock/geo/confidence.py` (modify) | `apply_submission_ceiling` |
| `gridlock/geo/run_all.py` (modify) | Call the ceiling |
| `gridlock/api/load_db.py` (modify) | Atomic database swap |
| `gridlock/api/rebuild.py` (create) | Background rebuild worker with coalescing |
| `gridlock/api/submissions.py` (create) | FastAPI router |
| `gridlock/api/main.py` (modify) | Mount the router |
| `gridlock/api/__init__.py`, `gridlock/api/tests/__init__.py` (create) | Make `api` an importable package for tests |
| `gridlock/web/index.html`, `styles.css` (modify) | Button, dialog, styles |
| `gridlock/web/submit-helpers.js` (create) | Pure helpers (unit-tested with node) |
| `gridlock/web/submit.js` (create) | Dialog behaviour |
| `gridlock/web/main.js` (modify) | Dashed marker and popup badge for submitted projects |
| `gridlock/data/interim/projects_report.csv` (create) | Committed baseline of parsed report rows |
| `md_artifacts/00_TEAM_CONTRACT.md` (modify) | Document the new files, columns, endpoints |
| `.gitignore` (modify) | Ignore runtime submission state |

---

### Task 1: Shared row helpers and the extended raw column list

**Files:**
- Modify: `gridlock/pipeline/common.py` (after `COLUMNS`)
- Modify: `gridlock/pipeline/classify.py` (append)
- Test: `gridlock/pipeline/tests/test_classify.py` (append), `gridlock/pipeline/tests/test_contract.py` (append)

**Interfaces:**
- Produces: `RAW_EXTRA: list[str]`, `RAW_COLUMNS: list[str]` (`COLUMNS + RAW_EXTRA`) in `pipeline.common`; `finalize_row(row: dict) -> dict` in `pipeline.classify` (mutates and returns `row`).

- [ ] **Step 1: Write the failing tests**

Append to `gridlock/pipeline/tests/test_classify.py`:

```python
from pipeline.classify import finalize_row


def test_finalize_row_sets_type_and_clears_endpoint_b_for_relay():
    relay = finalize_row({"project_name": "SCOTTDALE RELAY MODERNIZATION", "endpoint_b": "X"})
    assert relay["project_type"] == "relay" and relay["endpoint_b"] == ""
    line = finalize_row({"project_name": "OKATIE - BLUFFTON 115KV REBUILD", "endpoint_b": "BLUFFTON"})
    assert line["project_type"] == "rebuild" and line["endpoint_b"] == "BLUFFTON"
```

Append to `gridlock/pipeline/tests/test_contract.py`:

```python
from pipeline.common import RAW_COLUMNS


def test_raw_columns_extend_the_contract_without_reordering_it():
    assert RAW_COLUMNS[: len(COLUMNS)] == COLUMNS
    assert len(set(RAW_COLUMNS)) == len(RAW_COLUMNS)
    for extra in ("origin", "submission_id", "submitted_by", "submitted_at",
                  "given_lat_a", "given_lon_a", "given_lat_b", "given_lon_b"):
        assert extra in RAW_COLUMNS
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest gridlock/pipeline/tests/test_classify.py gridlock/pipeline/tests/test_contract.py -q`
Expected: FAIL with `ImportError: cannot import name 'finalize_row'` (and `RAW_COLUMNS`).

- [ ] **Step 3: Implement**

In `gridlock/pipeline/common.py`, directly after the `COLUMNS = [...]` list, add:

```python
RAW_EXTRA = [
    "origin", "submission_id", "submitted_by", "submitted_at",
    "given_lat_a", "given_lon_a", "given_lat_b", "given_lon_b",
]
RAW_COLUMNS = COLUMNS + RAW_EXTRA
```

Append to `gridlock/pipeline/classify.py`:

```python
def finalize_row(row):
    """Set project_type from the name; relay projects are single-site, so endpoint_b is cleared."""
    row["project_type"] = classify(row["project_name"])
    if row["project_type"] == "relay":
        row["endpoint_b"] = ""
    return row
```

- [ ] **Step 4: Run to verify they pass**

Run: `venv/bin/python -m pytest gridlock/pipeline -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add gridlock/pipeline/common.py gridlock/pipeline/classify.py gridlock/pipeline/tests/test_classify.py gridlock/pipeline/tests/test_contract.py
git commit -m "Add RAW_COLUMNS and finalize_row for submissions"
```

---

### Task 2: PDF reader

**Files:**
- Create: `gridlock/pipeline/pdf_submission.py`
- Test: `gridlock/pipeline/tests/test_pdf_submission.py`

**Interfaces:**
- Consumes: `pipeline.parse_gpc.parse_text(text, source_file) -> list[dict]`; `pipeline.parse_desc.parse_page(text, source_file) -> dict`; `pipeline.classify.finalize_row`.
- Produces: `read_pdf(data: bytes, utility: str, filename: str = "upload.pdf") -> list[dict]` (contract rows, `project_type` set); `SubmissionError(ValueError)`; `FileTooLarge(SubmissionError)`; `safe_name(filename) -> str`; constants `MAX_BYTES`, `MAX_PAGES`, `UTILITY_NAMES = {"GPC": "Georgia Power", "DESC": "Dominion Energy SC"}`.

- [ ] **Step 1: Write the failing tests**

Create `gridlock/pipeline/tests/test_pdf_submission.py`:

```python
from pathlib import Path

import pymupdf
import pytest

from pipeline import pdf_submission
from pipeline.pdf_submission import FileTooLarge, SubmissionError, read_pdf, safe_name

DESC_PAGE = """Project 43 of 44
Dominion Energy South Carolina
Planned Transmission Projects $2M and above Total
5 Year Budget
Urquhart - Aiken PSA 46 kV: Rebuild
Project ID
6810 O
Project Description
Rebuilding the section of 46 kV line from Urquhart to the Aiken PSA tap point. 4.5 miles.
Project Need
System hardening
Project Status
Planned
Planned In-Service Date
12/31/2027
Estimated Project Cost
Previous
2024
2025
2026
2027
2028
Total*
$0
$0
$0
$0
$3,000,000
$0
$3,000,000
"""

GPC_BLOCK = """Page 44 of 304
THALMANN AND COLERAIN 23O KV LINE RELAY PANEL UPGRADES
Teams # 21046
Need Date 06/01/2025 Start Date 12/01/2024
Description
"""

REPO = Path(__file__).resolve().parents[3]
REAL_DESC = REPO / "Sperry-Tech-Challenge" / "Project Listings" / "Dominion Energy" / "2024-2028-2million-and-above-project-descriptions.pdf"
REAL_GPC = REPO / "Sperry-Tech-Challenge" / "Project Listings" / "Georgia Power" / "2025 IRP Volume 3 PUBLIC DISCLOSURE.pdf"


def make_pdf(pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((36, 40), text, fontsize=7)
    data = doc.tobytes()
    doc.close()
    return data


def test_dominion_page_becomes_a_contract_row():
    rows = read_pdf(make_pdf([DESC_PAGE]), "DESC", "report.pdf")
    assert len(rows) == 1
    row = rows[0]
    assert row["project_id"] == "DESC_6810O" and row["utility"] == "DESC" and row["state"] == "SC"
    assert row["project_type"] == "rebuild"
    assert row["in_service_date"] == "2027-12-31" and row["est_cost_usd"] == 3000000
    assert row["source_file"] == "submission:report.pdf#page1"


def test_georgia_power_block_becomes_a_contract_row():
    rows = read_pdf(make_pdf([GPC_BLOCK]), "GPC", "irp.pdf")
    assert [r["project_id"] for r in rows] == ["GPC_21046"]
    assert rows[0]["project_type"] == "relay" and rows[0]["endpoint_b"] == ""
    assert rows[0]["voltage_kv"] == 230 and rows[0]["source_file"] == "submission:irp.pdf"


def test_wrong_company_selected_is_explained():
    with pytest.raises(SubmissionError, match="Dominion Energy SC PDF but you selected Georgia Power"):
        read_pdf(make_pdf([DESC_PAGE]), "GPC")


def test_not_a_pdf():
    with pytest.raises(SubmissionError, match="not a PDF"):
        read_pdf(b"hello world", "GPC")


def test_corrupt_pdf():
    with pytest.raises(SubmissionError, match="could not be opened"):
        read_pdf(b"%PDF-1.4 this is not really a pdf", "GPC")


def test_scanned_pdf_without_text():
    with pytest.raises(SubmissionError, match="no text"):
        read_pdf(make_pdf(["", ""]), "GPC")


def test_unrecognised_layout():
    with pytest.raises(SubmissionError, match="layout is not recognised"):
        read_pdf(make_pdf(["Quarterly newsletter\nNothing about projects here"]), "GPC")


def test_truncated_dominion_page_names_the_page():
    with pytest.raises(SubmissionError, match="Page 1"):
        read_pdf(make_pdf(["Project ID\nPlanned In-Service Date\n12/31/2027"]), "DESC")


def test_mixed_layouts_are_rejected():
    with pytest.raises(SubmissionError, match="mixes"):
        read_pdf(make_pdf([DESC_PAGE, GPC_BLOCK]), "DESC")


def test_oversized_upload(monkeypatch):
    monkeypatch.setattr(pdf_submission, "MAX_BYTES", 100)
    with pytest.raises(FileTooLarge, match="20 MB"):
        read_pdf(b"%PDF" + b"0" * 200, "GPC")


def test_too_many_pages(monkeypatch):
    monkeypatch.setattr(pdf_submission, "MAX_PAGES", 1)
    with pytest.raises(SubmissionError, match="limit is 1"):
        read_pdf(make_pdf([DESC_PAGE, DESC_PAGE]), "DESC")


def test_safe_name_strips_paths_and_odd_characters():
    assert safe_name("../../etc/passwd.pdf") == "passwd.pdf"
    assert safe_name("C:\\temp\\rép ort<>.pdf") == "rép ort__.pdf"
    assert safe_name("") == "upload.pdf"
    assert len(safe_name("x" * 500 + ".pdf")) == 100


@pytest.mark.skipif(not REAL_DESC.exists(), reason="source PDF not in the repo")
def test_real_dominion_report_gives_44_rows():
    rows = read_pdf(REAL_DESC.read_bytes(), "DESC", REAL_DESC.name)
    assert len(rows) == 44 and len({r["project_id"] for r in rows}) == 44


@pytest.mark.skipif(not REAL_GPC.exists(), reason="source PDF not in the repo")
def test_real_georgia_power_report_gives_208_rows():
    rows = read_pdf(REAL_GPC.read_bytes(), "GPC", REAL_GPC.name)
    assert len(rows) == 208
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest gridlock/pipeline/tests/test_pdf_submission.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.pdf_submission'`.

- [ ] **Step 3: Implement**

Create `gridlock/pipeline/pdf_submission.py`:

```python
"""Read a submitted PDF in one of our two report layouts into contract rows."""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from .classify import finalize_row
from .parse_desc import parse_page
from .parse_gpc import parse_text

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 800
UTILITY_NAMES = {"GPC": "Georgia Power", "DESC": "Dominion Energy SC"}


class SubmissionError(ValueError):
    """A problem with the upload that the submitter can act on; str(error) is safe to show."""


class FileTooLarge(SubmissionError):
    """The upload exceeds MAX_BYTES."""


def safe_name(filename):
    name = Path(str(filename or "upload.pdf").replace("\\", "/")).name
    name = re.sub(r"[^\w. \-]", "_", name).strip()
    return name[:100] or "upload.pdf"


def _is_dominion_page(text):
    return "Project ID" in text and "Planned In-Service Date" in text


def read_pdf(data, utility, filename="upload.pdf"):
    if len(data) > MAX_BYTES:
        raise FileTooLarge("The PDF is larger than 20 MB.")
    if not data.startswith(b"%PDF"):
        raise SubmissionError("This file is not a PDF.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as error:
        raise SubmissionError("The PDF could not be opened; it may be damaged.") from error
    with doc:
        if doc.page_count > MAX_PAGES:
            raise SubmissionError(f"The PDF has {doc.page_count} pages; the limit is {MAX_PAGES}.")
        pages = [page.get_text() for page in doc]
    if not "".join(pages).strip():
        raise SubmissionError("The PDF has no text (it looks scanned). Use the manual form instead.")

    source = f"submission:{safe_name(filename)}"
    text = "\n".join(pages)
    try:
        gpc_rows = parse_text(text, source) if re.search(r"^Teams # ", text, re.M) else []
    except (IndexError, ValueError) as error:
        raise SubmissionError("A Georgia Power project block could not be read.") from error
    desc_rows = []
    for number, page_text in enumerate(pages, 1):
        if not _is_dominion_page(page_text):
            continue
        try:
            desc_rows.append(parse_page(page_text, f"{source}#page{number}"))
        except (StopIteration, ValueError, IndexError) as error:
            raise SubmissionError(f"Page {number} looks like a Dominion project page but could not be read.") from error

    if gpc_rows and desc_rows:
        raise SubmissionError("This PDF mixes Georgia Power and Dominion layouts; upload them separately.")
    if not gpc_rows and not desc_rows:
        raise SubmissionError(
            "No projects found: the layout is not recognised. Upload a Georgia Power IRP or a Dominion "
            "project description PDF, or use the manual form."
        )
    detected = "GPC" if gpc_rows else "DESC"
    if detected != utility:
        raise SubmissionError(
            f"This looks like a {UTILITY_NAMES[detected]} PDF but you selected {UTILITY_NAMES[utility]}."
        )
    return [finalize_row(row) for row in (gpc_rows or desc_rows)]
```

- [ ] **Step 4: Run to verify they pass**

Run: `venv/bin/python -m pytest gridlock/pipeline/tests/test_pdf_submission.py -q`
Expected: all PASS (the two real-PDF tests take a few seconds).

- [ ] **Step 5: Commit**

```bash
git add gridlock/pipeline/pdf_submission.py gridlock/pipeline/tests/test_pdf_submission.py
git commit -m "Add PDF reader for submissions (Georgia Power and Dominion layouts)"
```

---

### Task 3: Submission store (form normalization, validation, diff, merge, locked log)

**Files:**
- Create: `gridlock/pipeline/submission_store.py`
- Test: `gridlock/pipeline/tests/test_submission_store.py`

**Interfaces:**
- Consumes: `finalize_row`; `COLUMNS`, `RAW_COLUMNS`, `RAW_EXTRA`, `clamp_window`, `endpoints`, `iso_date`, `max_kv` from `pipeline.common`; `STATE`, `validate` from `pipeline.validate`.
- Produces (all in `pipeline.submission_store`):
  - constants `SUBMISSIONS_CSV: Path`, `SUBMISSION_COLUMNS: list[str]`, `GIVEN: list[str]`, `ROW_KEYS: list[str]`
  - `prepare_form(payload: dict, taken_ids=()) -> tuple[dict, list[str]]` (row plus all error messages; empty row when the utility is invalid)
  - `validate_submission(row: dict) -> list[str]`
  - `clean_row(row: dict) -> dict` (only `ROW_KEYS`, all strings)
  - `diff(row: dict, current_by_id: dict[str, dict]) -> {"status": "new"|"update"|"unchanged", "changes": {field: [old, new]}}`
  - `merge_rows(report_rows: list[dict], submission_rows: list[dict]) -> list[dict]` (rows carry every `RAW_COLUMNS` key)
  - `read_submissions(path=None) -> list[dict]`, `append_submissions(rows, origin, submitted_by, path=None) -> list[str]` (new submission ids), `set_status(submission_id, status, path=None)` (raises `KeyError`), `history(path=None) -> list[dict]` (newest first)

- [ ] **Step 1: Write the failing tests**

Create `gridlock/pipeline/tests/test_submission_store.py`:

```python
import csv
import threading

import pytest

from pipeline import submission_store as store
from pipeline.common import RAW_COLUMNS
from pipeline.submission_store import (
    append_submissions, clean_row, diff, history, merge_rows, prepare_form,
    read_submissions, set_status, validate_submission,
)

FORM = {
    "utility": "GPC", "project_name": "Okatie - Bluffton 115kV: Rebuild",
    "endpoint_a": "Okatie", "endpoint_b": "Bluffton", "voltage_kv": "115 kV",
    "length_mi": "8.7 mi", "est_cost_usd": "$3,000,000", "in_service_date": "06/01/2026",
}


def report(**over):
    row = dict.fromkeys(RAW_COLUMNS, "")
    row.update(project_id="DESC_1", utility="DESC", state="SC", project_name="Hooks - Thurmond 115kV Tie: Rebuild",
               endpoint_a="Hooks", endpoint_b="Thurmond", voltage_kv="115", project_type="rebuild",
               in_service_date="2024-12-31", build_start="2024-01-01", build_end="2024-12-31")
    row.update(over)
    return row


# ---- prepare_form -----------------------------------------------------------

def test_form_values_are_normalised_to_the_contract():
    row, errors = prepare_form(FORM)
    assert errors == []
    assert row["project_id"] == "GPC_SUB1" and row["state"] == "GA" and row["utility"] == "GPC"
    assert row["voltage_kv"] == "115" and row["est_cost_usd"] == "3000000" and row["length_mi"] == "8.7"
    assert row["in_service_date"] == "2026-06-01"
    assert (row["build_start"], row["build_end"]) == ("2026-01-01", "2026-06-01")
    assert row["project_type"] == "rebuild" and row["source_file"] == "form"


def test_lowercase_utility_and_stray_whitespace_are_accepted():
    row, errors = prepare_form({**FORM, "utility": " gpc ", "project_name": "  Okatie -\n Bluffton   115kV  Rebuild "})
    assert errors == [] and row["utility"] == "GPC" and "\n" not in row["project_name"]
    assert "  " not in row["project_name"]


def test_endpoints_and_voltage_are_derived_from_the_name_when_left_blank():
    row, errors = prepare_form({"utility": "DESC", "project_name": "Okatie-Bluffton 115kV: Rebuild", "in_service_date": "2026-06-01"})
    assert errors == [] and (row["endpoint_a"], row["endpoint_b"], row["voltage_kv"]) == ("Okatie", "Bluffton", "115")


@pytest.mark.parametrize("field,value,fragment", [
    ("voltage_kv", "abc", "voltage_kv"),
    ("est_cost_usd", "1.2.3", "est_cost_usd"),
    ("in_service_date", "13/45/2026", "in_service_date"),
    ("in_service_date", "next spring", "in_service_date"),
    ("build_start", "2027-01-01", "build_start"),
    ("project_name", "", "project_name"),
    ("in_service_date", "", "in_service_date"),
    ("utility_project_id", "bad id/with slash", "utility_project_id"),
    ("project_name", "=HYPERLINK(\"http://x\")", "must not start"),
])
def test_bad_form_values_are_reported_by_field(field, value, fragment):
    payload = {**FORM, field: value}
    row, errors = prepare_form(payload)
    assert any(fragment in e for e in errors), errors


def test_invalid_utility_returns_no_row():
    row, errors = prepare_form({**FORM, "utility": "XYZ"})
    assert row == {} and errors


def test_user_ids_get_the_prefix_and_generated_ids_skip_taken_ones():
    assert prepare_form({**FORM, "utility_project_id": "20 277"})[0]["project_id"] == "GPC_20277"
    assert prepare_form({**FORM, "utility_project_id": "GPC_20277"})[0]["project_id"] == "GPC_20277"
    assert prepare_form(FORM, taken_ids={"GPC_SUB1", "GPC_SUB2"})[0]["project_id"] == "GPC_SUB3"


@pytest.mark.parametrize("coords,fragment", [
    ({"lat_a": "-81.1", "lon_a": "32.3"}, "outside Georgia and South Carolina"),
    ({"lat_a": "40.0", "lon_a": "-81.1"}, "outside Georgia and South Carolina"),
    ({"lat_a": "32.3"}, "both latitude and longitude"),
    ({"lat_b": "32.3", "lon_b": "-81.1", "endpoint_b": ""}, "without a name"),
])
def test_bad_coordinates_are_rejected(coords, fragment):
    row, errors = prepare_form({**FORM, **coords})
    assert any(fragment in e for e in errors), errors


def test_good_coordinates_are_kept_as_given_coordinates():
    row, errors = prepare_form({**FORM, "lat_a": "32.2776", "lon_a": "-80.9686"})
    assert errors == [] and (row["given_lat_a"], row["given_lon_a"]) == ("32.2776", "-80.9686")


def test_validate_submission_rejects_forged_or_unsafe_rows():
    row, _ = prepare_form(FORM)
    assert validate_submission(row) == []
    assert validate_submission({**row, "project_id": "GPC_../x"})
    assert validate_submission({**row, "project_name": "x" * 201})
    assert validate_submission({**row, "endpoint_a": ""})


def test_clean_row_keeps_only_row_keys_as_strings():
    row, _ = prepare_form(FORM)
    forged = {**row, "status": "rejected", "submission_id": "sub_evil", "voltage_kv": 115}
    cleaned = clean_row(forged)
    assert "status" not in cleaned and "submission_id" not in cleaned and cleaned["voltage_kv"] == "115"


# ---- diff ---------------------------------------------------------------------

def test_diff_new_update_unchanged_and_numeric_equality():
    current = {"DESC_1": report(length_mi="18.0", in_service_date="2024-12-31")}
    assert diff({"project_id": "DESC_9", "project_name": "x"}, current)["status"] == "new"
    update = diff({"project_id": "DESC_1", "in_service_date": "2025-06-01"}, current)
    assert update == {"status": "update", "changes": {"in_service_date": ["2024-12-31", "2025-06-01"]}}
    assert diff({"project_id": "DESC_1", "length_mi": "18", "in_service_date": "2024-12-31"}, current)["status"] == "unchanged"
    assert diff({"project_id": "DESC_1", "in_service_date": ""}, current)["status"] == "unchanged"


# ---- merge --------------------------------------------------------------------

def sub(**over):
    row = dict.fromkeys(store.SUBMISSION_COLUMNS, "")
    row.update(project_id="DESC_1", utility="DESC", state="SC", origin="form", submission_id="sub_1",
               submitted_at="2026-09-27T10:00:00.000000Z", status="active", submitted_by="Dominion Energy SC")
    row.update(over)
    return row


def test_merge_override_blank_keeps_existing_and_new_ids_are_appended():
    merged = merge_rows([report()], [sub(in_service_date="2025-06-01", project_name=""), sub(project_id="DESC_SUB1", project_name="New line - X 115kV", submission_id="sub_2")])
    by_id = {r["project_id"]: r for r in merged}
    assert by_id["DESC_1"]["in_service_date"] == "2025-06-01"
    assert by_id["DESC_1"]["project_name"] == "Hooks - Thurmond 115kV Tie: Rebuild"
    assert by_id["DESC_1"]["origin"] == "form" and by_id["DESC_1"]["submission_id"] == "sub_1"
    assert "DESC_SUB1" in by_id and len(merged) == 2
    assert all(set(r) == set(RAW_COLUMNS) for r in merged)


def test_report_rows_get_origin_report():
    assert merge_rows([report()], [])[0]["origin"] == "report"


def test_latest_active_submission_wins_and_rejected_ones_are_ignored():
    early = sub(in_service_date="2025-01-01", submission_id="sub_a", submitted_at="2026-09-27T09:00:00.000000Z")
    late = sub(in_service_date="2026-01-01", submission_id="sub_b", submitted_at="2026-09-27T10:00:00.000000Z")
    assert merge_rows([report()], [early, late])[0]["in_service_date"] == "2026-01-01"
    rejected = {**late, "status": "rejected"}
    assert merge_rows([report()], [early, rejected])[0]["in_service_date"] == "2025-01-01"
    assert merge_rows([report()], [{**early, "status": "rejected"}, rejected])[0]["in_service_date"] == "2024-12-31"


def test_relay_rule_is_reapplied_after_a_merge():
    merged = merge_rows([report()], [sub(project_name="Hooks RELAY MODERNIZATION")])
    assert merged[0]["project_type"] == "relay" and merged[0]["endpoint_b"] == ""


# ---- storage ------------------------------------------------------------------

def test_append_read_status_and_history(tmp_path):
    path = tmp_path / "submissions.csv"
    assert read_submissions(path) == []
    row, _ = prepare_form(FORM)
    ids = append_submissions([row], "form", "Georgia Power (Ana)", path)
    assert len(ids) == 1 and ids[0].startswith("sub_")
    saved = read_submissions(path)[0]
    assert saved["status"] == "active" and saved["origin"] == "form" and saved["submitted_by"] == "Georgia Power (Ana)"
    assert saved["submitted_at"].endswith("Z") and saved["project_id"] == "GPC_SUB1"
    set_status(ids[0], "rejected", path)
    assert read_submissions(path)[0]["status"] == "rejected"
    set_status(ids[0], "active", path)
    assert history(path)[0]["submission_id"] == ids[0]
    with pytest.raises(KeyError):
        set_status("sub_missing", "rejected", path)


def test_history_is_newest_first(tmp_path):
    path = tmp_path / "s.csv"
    first = append_submissions([prepare_form(FORM)[0]], "form", "a", path)[0]
    second = append_submissions([prepare_form({**FORM, "utility_project_id": "2"})[0]], "form", "a", path)[0]
    assert [h["submission_id"] for h in history(path)] == [second, first]


def test_concurrent_appends_lose_nothing_and_leave_no_temp_files(tmp_path):
    path = tmp_path / "s.csv"
    errors = []

    def worker(n):
        try:
            for i in range(5):
                row, _ = prepare_form({**FORM, "utility_project_id": f"{n}-{i}"})
                append_submissions([row], "form", f"t{n}", path)
        except Exception as error:  # pragma: no cover - the assertion below reports it
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    rows = read_submissions(path)
    assert len(rows) == 40 and len({r["submission_id"] for r in rows}) == 40
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".tmp") == []
    with path.open(newline="", encoding="utf-8") as f:
        assert csv.DictReader(f).fieldnames == store.SUBMISSION_COLUMNS
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest gridlock/pipeline/tests/test_submission_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.submission_store'`.

- [ ] **Step 3: Implement**

Create `gridlock/pipeline/submission_store.py`:

```python
"""Submission storage: form normalization, validation, diffing, merging and the append-only revision log."""
from __future__ import annotations

import csv
import fcntl
import os
import re
import secrets
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .classify import finalize_row
from .common import COLUMNS, RAW_COLUMNS, RAW_EXTRA, clamp_window, endpoints, iso_date, max_kv
from .validate import STATE, validate

ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS_CSV = ROOT / "data" / "interim" / "submissions.csv"
SUBMISSION_COLUMNS = COLUMNS + RAW_EXTRA + ["status"]
GIVEN = ["given_lat_a", "given_lon_a", "given_lat_b", "given_lon_b"]
ROW_KEYS = COLUMNS + GIVEN
BBOX = (30.3, 35.3, -85.7, -78.5)  # min lat, max lat, min lon, max lon: Georgia and South Carolina
NUMERIC = {"voltage_kv", "length_mi", "est_cost_usd"}
COMPARE_FIELDS = [
    "project_name", "endpoint_a", "endpoint_b", "voltage_kv", "project_type", "length_mi",
    "est_cost_usd", "start_date", "in_service_date", "build_start", "build_end",
] + GIVEN


# ---- form normalization ------------------------------------------------------------

def _text(value):
    return " ".join(str(value if value is not None else "").split())


def _number(value):
    text = re.sub(r"[^\d.\-]", "", str(value if value is not None else ""))
    if text in ("", "-", "."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _numeric_field(payload, key, whole, errors):
    raw = _text(payload.get(key))
    if not raw:
        return ""
    number = _number(raw)
    if number is None:
        errors.append(f"{key}: {raw!r} is not a number")
        return ""
    if whole:
        return str(int(round(number)))
    return str(int(number)) if number == int(number) else str(number)


def _date_field(payload, key, errors):
    raw = _text(payload.get(key))
    if not raw:
        return ""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            datetime.strptime(raw, "%Y-%m-%d")
            return raw
        iso = iso_date(raw)
    except ValueError:
        iso = ""
    if not iso:
        errors.append(f"{key}: {raw!r} is not a date (use YYYY-MM-DD)")
    return iso


def _coordinate_field(payload, key, errors):
    raw = _text(payload.get(key))
    if not raw:
        return ""
    try:
        return str(float(raw))
    except ValueError:
        errors.append(f"{key}: {raw!r} is not a number")
        return ""


def _generated_id(utility, taken_ids):
    taken = set(taken_ids)
    n = 1
    while f"{utility}_SUB{n}" in taken:
        n += 1
    return f"{utility}_SUB{n}"


def prepare_form(payload, taken_ids=()):
    """Turn form input into a contract row. Returns (row, errors); the row is {} when the utility is invalid."""
    errors = []
    utility = _text(payload.get("utility")).upper()
    if utility not in STATE:
        return {}, ["utility: choose Georgia Power (GPC) or Dominion Energy SC (DESC)"]
    name = _text(payload.get("project_name"))
    a_name, b_name = _text(payload.get("endpoint_a")), _text(payload.get("endpoint_b"))
    if not a_name and not b_name:
        a_name, b_name = endpoints(name)
    elif not a_name:
        a_name, b_name = b_name, ""

    raw_id = re.sub(r"\s+", "", _text(payload.get("utility_project_id")))
    if raw_id.upper().startswith(f"{utility}_"):
        raw_id = raw_id[len(utility) + 1:]
    if raw_id and not re.fullmatch(r"[\w.,\-]+", raw_id):
        errors.append(f"utility_project_id: {raw_id!r} may only contain letters, digits and . , _ -")
        raw_id = ""
    project_id = f"{utility}_{raw_id}" if raw_id else _generated_id(utility, taken_ids)

    in_service = _date_field(payload, "in_service_date", errors)
    start = _date_field(payload, "build_start", errors)
    if start and in_service and start > in_service:
        errors.append("build_start: is after in_service_date")
    default_start = f"{in_service[:4]}-01-01" if in_service else ""
    build_start, build_end = clamp_window(start or default_start, in_service)
    voltage = _numeric_field(payload, "voltage_kv", True, errors) or (str(max_kv(name)) if max_kv(name) else "")

    row = dict.fromkeys(ROW_KEYS, "")
    row.update(
        project_id=project_id, utility=utility, state=STATE[utility], project_name=name,
        endpoint_a=a_name, endpoint_b=b_name, voltage_kv=voltage,
        length_mi=_numeric_field(payload, "length_mi", False, errors),
        est_cost_usd=_numeric_field(payload, "est_cost_usd", True, errors),
        start_date=start, in_service_date=in_service, build_start=build_start, build_end=build_end,
        source_file="form", source_ref="manual entry",
        given_lat_a=_coordinate_field(payload, "lat_a", errors), given_lon_a=_coordinate_field(payload, "lon_a", errors),
        given_lat_b=_coordinate_field(payload, "lat_b", errors), given_lon_b=_coordinate_field(payload, "lon_b", errors),
    )
    finalize_row(row)
    errors += validate_submission(row)
    return row, list(dict.fromkeys(errors))


# ---- validation ---------------------------------------------------------------------

def _coordinate_errors(row):
    errors = []
    for side in ("a", "b"):
        lat, lon = row.get(f"given_lat_{side}", ""), row.get(f"given_lon_{side}", "")
        label = f"endpoint {side.upper()}"
        if (lat == "") != (lon == ""):
            errors.append(f"{label}: give both latitude and longitude")
            continue
        if lat == "":
            continue
        try:
            la, lo = float(lat), float(lon)
        except ValueError:
            errors.append(f"{label}: coordinates must be numbers")
            continue
        if not (BBOX[0] <= la <= BBOX[1] and BBOX[2] <= lo <= BBOX[3]):
            errors.append(f"{label}: ({la}, {lo}) is outside Georgia and South Carolina (latitude first, longitude negative)")
        if not row.get(f"endpoint_{side}"):
            errors.append(f"{label}: coordinates given without a name")
    return errors


def validate_submission(row):
    """Every problem that would stop this row being saved, as plain messages."""
    errors = [m.split(": ", 1)[1] if ": " in m else m for m in validate([row])]
    for key in ("project_name", "endpoint_a", "endpoint_b"):
        value = str(row.get(key) or "")
        if value[:1] in ("=", "+", "@"):
            errors.append(f"{key}: must not start with {value[:1]!r}")
    if len(str(row.get("project_name") or "")) > 200:
        errors.append("project_name: longer than 200 characters")
    if not row.get("endpoint_a"):
        errors.append("endpoint_a: give at least one substation name")
    project_id = str(row.get("project_id") or "")
    if not re.fullmatch(r"(GPC|DESC)_[\w.,\-]+", project_id):
        errors.append(f"project_id: {project_id!r} is not valid")
    errors += _coordinate_errors(row)
    return list(dict.fromkeys(errors))


def clean_row(row):
    """Only the row keys, as strings: drops anything a client added (status, submission_id, ...)."""
    return {key: "" if row.get(key) is None else str(row.get(key)) for key in ROW_KEYS}


# ---- diff and merge -----------------------------------------------------------------

def _same(field, old, new):
    if field in NUMERIC:
        try:
            return float(old) == float(new)
        except ValueError:
            pass
    return old == new


def diff(row, current_by_id):
    current = current_by_id.get(row["project_id"])
    if current is None:
        return {"status": "new", "changes": {}}
    changes = {}
    for field in COMPARE_FIELDS:
        new, old = str(row.get(field, "") or ""), str(current.get(field, "") or "")
        if new != "" and not _same(field, old, new):
            changes[field] = [old, new]
    return {"status": "update" if changes else "unchanged", "changes": changes}


def merge_rows(report_rows, submission_rows):
    """Report rows with the latest active submission per project laid over them."""
    merged, order, touched = {}, [], set()
    for row in report_rows:
        base = dict.fromkeys(RAW_COLUMNS, "")
        base.update({k: ("" if v is None else v) for k, v in row.items() if k in RAW_COLUMNS})
        base["origin"] = base["origin"] or "report"
        merged[base["project_id"]] = base
        order.append(base["project_id"])
    active = sorted((s for s in submission_rows if s.get("status", "active") == "active"),
                    key=lambda s: (s["submitted_at"], s["submission_id"]))
    for submission in active:
        pid = submission["project_id"]
        if pid not in merged:
            merged[pid] = dict.fromkeys(RAW_COLUMNS, "")
            order.append(pid)
        touched.add(pid)
        for column in RAW_COLUMNS:
            value = submission.get(column, "")
            if value not in ("", None):
                merged[pid][column] = value
    for pid in touched:
        finalize_row(merged[pid])
    return [merged[pid] for pid in order]


# ---- the locked, append-only log ------------------------------------------------------

@contextmanager
def _locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _resolve(path):
    return Path(path) if path else SUBMISSIONS_CSV


def read_submissions(path=None):
    path = _resolve(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [{col: row.get(col, "") for col in SUBMISSION_COLUMNS} for row in csv.DictReader(handle)]


def _write_all(path, rows):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=SUBMISSION_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_submissions(rows, origin, submitted_by, path=None):
    path = _resolve(path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    ids = []
    with _locked(path):
        existing = read_submissions(path)
        for row in rows:
            entry = dict.fromkeys(SUBMISSION_COLUMNS, "")
            entry.update({k: v for k, v in row.items() if k in SUBMISSION_COLUMNS})
            submission_id = "sub_" + secrets.token_hex(4)
            entry.update(submission_id=submission_id, origin=origin, submitted_by=_text(submitted_by),
                         submitted_at=now, status="active")
            existing.append(entry)
            ids.append(submission_id)
        _write_all(path, existing)
    return ids


def set_status(submission_id, status, path=None):
    path = _resolve(path)
    with _locked(path):
        rows = read_submissions(path)
        for row in rows:
            if row["submission_id"] == submission_id:
                row["status"] = status
                _write_all(path, rows)
                return
    raise KeyError(submission_id)


def history(path=None):
    return sorted(read_submissions(path), key=lambda r: (r["submitted_at"], r["submission_id"]), reverse=True)
```

- [ ] **Step 4: Run to verify they pass**

Run: `venv/bin/python -m pytest gridlock/pipeline/tests/test_submission_store.py -q`
Expected: all PASS. If `test_history_is_newest_first` is flaky because two appends share a microsecond, that is a real bug: `submitted_at` has microseconds and `submission_id` breaks ties, so re-run once and, if it fails again, stop and investigate rather than loosening the test.

- [ ] **Step 5: Commit**

```bash
git add gridlock/pipeline/submission_store.py gridlock/pipeline/tests/test_submission_store.py
git commit -m "Add submission store: form normalization, validation, diff, merge, locked log"
```

---

### Task 4: `build_raw` merges submissions onto a committed baseline

**Files:**
- Modify: `gridlock/pipeline/build_raw.py` (rewrite)
- Modify: `gridlock/pipeline/validate.py` (columns check)
- Modify: `gridlock/pipeline/tests/test_contract.py` (real-CSV test)
- Create: `gridlock/data/interim/projects_report.csv` (generated)
- Test: `gridlock/pipeline/tests/test_build_merge.py`
- Regenerated: `gridlock/data/interim/projects_raw.csv`, `gridlock/data/processed/*.csv`

**Interfaces:**
- Consumes: `merge_rows`, `read_submissions` from Task 3; `finalize_row`; `RAW_COLUMNS`, `COLUMNS`.
- Produces: `build(raw=None, baseline=None, submissions=None) -> list[dict]` (merged rows with every `RAW_COLUMNS` key); `write(rows, out=None, columns=None)`; module constants `RAW`, `INTERIM`, `BASELINE`, `OUT`. `report_rows()` parses the report text when `data/raw` has it (and refreshes the baseline) and otherwise reads the committed baseline.

- [ ] **Step 1: Write the failing test**

Create `gridlock/pipeline/tests/test_build_merge.py`:

```python
import csv

from pipeline import build_raw
from pipeline.common import COLUMNS, RAW_COLUMNS
from pipeline.submission_store import SUBMISSION_COLUMNS


def write_csv(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def baseline_row(**over):
    row = dict.fromkeys(COLUMNS, "")
    row.update(project_id="DESC_1", utility="DESC", state="SC", project_name="Hooks - Thurmond 115kV Tie: Rebuild",
               endpoint_a="Hooks", endpoint_b="Thurmond", voltage_kv="115", project_type="rebuild",
               in_service_date="2024-12-31", build_start="2024-01-01", build_end="2024-12-31")
    row.update(over)
    return row


def submission_row(**over):
    row = dict.fromkeys(SUBMISSION_COLUMNS, "")
    row.update(project_id="DESC_1", utility="DESC", state="SC", origin="pdf", submission_id="sub_1",
               submitted_at="2026-09-27T10:00:00.000000Z", status="active", in_service_date="2025-06-01")
    row.update(over)
    return row


def test_build_uses_the_baseline_when_report_text_is_missing_and_merges_submissions(tmp_path):
    baseline = tmp_path / "projects_report.csv"
    submissions = tmp_path / "submissions.csv"
    write_csv(baseline, COLUMNS, [baseline_row()])
    write_csv(submissions, SUBMISSION_COLUMNS, [submission_row(), submission_row(project_id="DESC_SUB1", project_name="New - Line 115kV", submission_id="sub_2", state="SC")])
    rows = build_raw.build(raw=tmp_path / "no-report-text", baseline=baseline, submissions=submissions)
    by_id = {r["project_id"]: r for r in rows}
    assert by_id["DESC_1"]["in_service_date"] == "2025-06-01" and by_id["DESC_1"]["origin"] == "pdf"
    assert by_id["DESC_1"]["project_name"].startswith("Hooks")
    assert by_id["DESC_SUB1"]["origin"] == "pdf" and len(rows) == 2


def test_write_uses_the_extended_columns(tmp_path):
    baseline = tmp_path / "b.csv"
    write_csv(baseline, COLUMNS, [baseline_row()])
    rows = build_raw.build(raw=tmp_path / "none", baseline=baseline, submissions=tmp_path / "none.csv")
    out = tmp_path / "raw.csv"
    build_raw.write(rows, out)
    with out.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)
    assert reader.fieldnames == RAW_COLUMNS and data[0]["origin"] == "report"


def test_missing_baseline_and_report_text_is_a_clear_error(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError, match="projects_report.csv"):
        build_raw.build(raw=tmp_path / "none", baseline=tmp_path / "projects_report.csv", submissions=tmp_path / "none.csv")
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m pytest gridlock/pipeline/tests/test_build_merge.py -q`
Expected: FAIL (`build()` does not accept those arguments).

- [ ] **Step 3: Implement**

Replace `gridlock/pipeline/build_raw.py` with:

```python
"""Build data/interim/projects_raw.csv: parsed report rows (baseline) with submissions laid over them."""
import csv
from collections import Counter
from pathlib import Path

from .classify import finalize_row
from .common import COLUMNS, RAW_COLUMNS
from .parse_desc import parse_all as parse_desc_all
from .parse_gpc import parse_all as parse_gpc_all
from .submission_store import merge_rows, read_submissions
from .validate import validate

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
BASELINE = INTERIM / "projects_report.csv"
OUT = INTERIM / "projects_raw.csv"


def read_rows(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write(rows, out=None, columns=None):
    out = Path(out) if out else OUT
    columns = columns or RAW_COLUMNS
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r[k]) for k in columns})


def report_rows(raw=None, baseline=None):
    """Parsed report rows.

    The extracted report text is regenerable and gitignored, so when it is absent the committed
    baseline (written the last time the text was parsed) stands in.
    """
    raw = Path(raw) if raw else RAW
    baseline = Path(baseline) if baseline else BASELINE
    if (raw / "desc_pages").exists() and (raw / "gpc_irp_vol3.txt").exists():
        rows = [finalize_row(r) for r in parse_desc_all(raw / "desc_pages") + parse_gpc_all(raw / "gpc_irp_vol3.txt")]
        write(rows, baseline, columns=COLUMNS)
        return rows
    if baseline.exists():
        return read_rows(baseline)
    raise FileNotFoundError(f"No report text in {raw} and no baseline {baseline.name}; run pipeline/extract_pdfs.py first")


def build(raw=None, baseline=None, submissions=None):
    return merge_rows(report_rows(raw, baseline), read_submissions(submissions))


def report(rows):
    lines = [f"rows: {len(rows)}"]
    lines.append("by utility: " + str(dict(Counter(r["utility"] for r in rows))))
    lines.append("by type: " + str(dict(Counter(r["project_type"] for r in rows))))
    lines.append("by origin: " + str(dict(Counter(r["origin"] for r in rows))))
    kv = sum(1 for r in rows if r["voltage_kv"])
    lines.append(f"with voltage_kv: {kv}/{len(rows)}")
    dates = sorted(r["in_service_date"] for r in rows if r["in_service_date"])
    lines.append(f"in_service_date range: {dates[0]} to {dates[-1]}")
    return "\n".join(lines)


if __name__ == "__main__":
    data = build()
    write(data)
    print(report(data))
    problems = validate(data)
    print("contract violations:", len(problems))
    for p in problems[:20]:
        print(" -", p)
    raise SystemExit(1 if problems else 0)
```

In `gridlock/pipeline/validate.py`, change the import and the columns check:

```python
from .common import RAW_COLUMNS
...
    if columns is not None and list(columns) != RAW_COLUMNS:
        errs.append(f"columns differ from contract: {columns}")
```

In `gridlock/pipeline/tests/test_contract.py`, change `test_real_csv_meets_contract` to compare `reader.fieldnames == RAW_COLUMNS` (the import from Task 1 already exists).

- [ ] **Step 4: Regenerate the data and verify**

Run:
```bash
PYTHONPATH=gridlock venv/bin/python -m pipeline.build_raw
venv/bin/python -m pytest gridlock/pipeline -q
```
Expected: `rows: 252`, `by origin: {'report': 252}`, `contract violations: 0`; all tests PASS. `gridlock/data/interim/projects_report.csv` now exists with 252 rows.

Then confirm the geo pipeline still runs with the extra columns (this uses cached data and takes about 10 seconds):

```bash
venv/bin/python gridlock/geo/run_all.py
venv/bin/python -m pytest gridlock -q
```
Expected: `Projects: 252; overlaps: 47`, all tests PASS, and `head -1 gridlock/data/processed/projects.csv` now includes `origin,submission_id,submitted_by,submitted_at,given_lat_a`.

- [ ] **Step 5: Commit**

```bash
git add gridlock/pipeline gridlock/data/interim gridlock/data/processed
git commit -m "build_raw: merge submissions onto a committed baseline of report rows"
```

---

### Task 5: Given coordinates and the confidence ceiling

**Files:**
- Modify: `gridlock/geo/geocode.py` (`geocode_project`, add `_given_matches`)
- Modify: `gridlock/geo/confidence.py` (add `SUBMISSION_CEILING`, `apply_submission_ceiling`)
- Modify: `gridlock/geo/run_all.py` (import and call)
- Test: `gridlock/geo/test_submission_geo.py`

**Interfaces:**
- Consumes: raw rows may carry `given_lat_a`, `given_lon_a`, `given_lat_b`, `given_lon_b`, `origin` (Task 4).
- Produces: `geocode_project` sets method `submitted_coordinates` for endpoints located by given coordinates, with `osm_id_*` = `"submitted"`; `apply_submission_ceiling(project: dict) -> None`; `SUBMISSION_CEILING = 0.6`.

- [ ] **Step 1: Write the failing tests**

Create `gridlock/geo/test_submission_geo.py`:

```python
from confidence import SUBMISSION_CEILING, apply_submission_ceiling, score_project
from geocode import geocode_project


def sub(osm_id, lat, lon, name, state="SC", operator="Dominion Energy"):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"osm_id": osm_id, "name": name, "gridlock_state": state, "operator": operator}}


def project(**over):
    row = {"project_id": "DESC_SUB1", "utility": "DESC", "state": "SC", "project_name": "Okatie - Bluffton 115kV: Rebuild",
           "endpoint_a": "Okatie", "endpoint_b": "Bluffton", "voltage_kv": "115", "length_mi": "",
           "given_lat_a": "", "given_lon_a": "", "given_lat_b": "", "given_lon_b": "", "origin": "form"}
    row.update(over)
    return row


FEATURES = [sub("bluffton", 32.235, -80.853, "Bluffton Substation"), sub("okatie-wrong", 34.0, -81.0, "Okatie Substation")]


def test_given_coordinates_locate_the_endpoint_and_skip_name_matching():
    located, matches = geocode_project(project(given_lat_a="32.2776", given_lon_a="-80.9686"), FEATURES)
    assert (located["lat_a"], located["lon_a"]) == (32.2776, -80.9686)
    assert located["osm_id_a"] == "submitted"
    assert located["geocode_method"] == "a:submitted_coordinates;b:name"
    assert located["osm_id_b"] == "bluffton"


def test_without_given_coordinates_behaviour_is_unchanged():
    located, _ = geocode_project(project(), FEATURES)
    assert located["geocode_method"].startswith("a:name")


def test_given_coordinates_score_as_a_confident_endpoint():
    located, matches = geocode_project(project(endpoint_b="", given_lat_a="32.2776", given_lon_a="-80.9686"), FEATURES)
    scored = score_project(located, matches)
    assert scored["confidence"] >= 0.8


def test_unverified_submissions_are_capped_and_reports_are_not():
    submitted = {"origin": "form", "confidence": 0.95, "confidence_tier": "high", "human_verified": "false"}
    apply_submission_ceiling(submitted)
    assert submitted["confidence"] == SUBMISSION_CEILING == 0.6 and submitted["confidence_tier"] == "medium"
    report = {"origin": "report", "confidence": 0.95, "confidence_tier": "high", "human_verified": "false"}
    apply_submission_ceiling(report)
    assert report["confidence"] == 0.95 and report["confidence_tier"] == "high"
    legacy = {"confidence": 0.95, "confidence_tier": "high", "human_verified": "false"}
    apply_submission_ceiling(legacy)
    assert legacy["confidence"] == 0.95


def test_the_ceiling_keeps_low_scores_and_unmatched_tier():
    low = {"origin": "pdf", "confidence": 0.3, "confidence_tier": "low", "human_verified": "false"}
    apply_submission_ceiling(low)
    assert low["confidence"] == 0.3 and low["confidence_tier"] == "low"
    unmatched = {"origin": "pdf", "confidence": 0.0, "confidence_tier": "unmatched", "human_verified": "false"}
    apply_submission_ceiling(unmatched)
    assert unmatched["confidence_tier"] == "unmatched"


def test_verified_submissions_are_left_alone():
    verified = {"origin": "form", "confidence": 1.0, "confidence_tier": "high", "human_verified": "true"}
    apply_submission_ceiling(verified)
    assert verified["confidence"] == 1.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest gridlock/geo/test_submission_geo.py -q`
Expected: FAIL (`ImportError: cannot import name 'SUBMISSION_CEILING'`).

- [ ] **Step 3: Implement**

In `gridlock/geo/geocode.py`, add this function directly above `def geocode_project`:

```python
def _given_matches(project: dict) -> dict:
    """Endpoints the submitter located by coordinates: taken as-is, no name matching."""
    given = {}
    for suffix in ("a", "b"):
        lat, lon = project.get(f"given_lat_{suffix}"), project.get(f"given_lon_{suffix}")
        if lat in ("", None) or lon in ("", None):
            continue
        given[suffix] = {
            "feature": {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                "properties": {"osm_id": "submitted", "gridlock_state": project["state"]},
            },
            "name_score": 100,
            "given": True,
        }
    return given
```

In `geocode_project`, directly after the loop that fills `cands` (the line `cands[suffix] = _in_hint_area(project, found)`) and before `both = bool(cands["a"] and cands["b"])`, insert:

```python
    for suffix, given_match in _given_matches(project).items():
        cands[suffix] = [given_match]
```

Replace the `methods = {...}` line with:

```python
    methods = {
        s: ("submitted_coordinates" if m.get("given") else "name_relaxed" if m.get("relaxed") else "name")
        for s, m in matches.items() if m
    }
```

In `gridlock/geo/confidence.py`, add after `INFERRED_CEILING`:

```python
SUBMISSION_CEILING = 0.6   # an unverified submission is "medium" at best
```

and append at the end of the file:

```python
def apply_submission_ceiling(project: dict) -> None:
    """Submitted projects stay 'medium' at best until someone verifies them (manual_fixes.csv lifts this)."""
    if project.get("origin", "report") in ("", "report") or project.get("human_verified") == "true":
        return
    score = min(float(project["confidence"]), SUBMISSION_CEILING)
    project["confidence"] = round(score, 3)
    project["confidence_tier"] = tier_for(score, project["confidence_tier"] != "unmatched")
```

In `gridlock/geo/run_all.py`, change the import to `from confidence import apply_route_evidence, apply_submission_ceiling, score_project` and, immediately before the line `apply_manual_fixes(projects, output / "manual_fixes.csv")`, add:

```python
    for project in projects:
        apply_submission_ceiling(project)
```

- [ ] **Step 4: Run to verify they pass**

Run: `venv/bin/python -m pytest gridlock -q`
Expected: all PASS (the existing geo tests still pass because reports and rows without `given_*` behave as before).

- [ ] **Step 5: Commit**

```bash
git add gridlock/geo
git commit -m "Geocoder: honour submitted coordinates; cap unverified submissions at medium"
```

---

### Task 6: Atomic database swap and the rebuild worker

**Files:**
- Modify: `gridlock/api/load_db.py` (`main`, add `import os`)
- Create: `gridlock/api/__init__.py` (empty), `gridlock/api/tests/__init__.py` (empty)
- Create: `gridlock/api/rebuild.py`
- Test: `gridlock/api/tests/test_load_db.py`, `gridlock/api/tests/test_rebuild.py`

**Interfaces:**
- Produces: `api.rebuild.Rebuilder(commands=None, cwd=ROOT, timeout=900)` with `request() -> str` (job id, non-blocking), `status(job_id) -> {"status": "queued"|"running"|"done"|"failed", "message": str} | None`; `api.rebuild.default_commands()`.
- Behaviour: at most one rebuild runs at a time; requests that arrive during a run are served by one follow-up run (coalescing), so all their jobs finish after data written before the follow-up started.

- [ ] **Step 1: Write the failing tests**

Create empty files `gridlock/api/__init__.py` and `gridlock/api/tests/__init__.py`.

Create `gridlock/api/tests/test_load_db.py`:

```python
import sqlite3
import sys

import pytest

from api import load_db


def write_processed(root, projects_rows):
    folder = root / "data" / "processed"
    folder.mkdir(parents=True)
    (folder / "projects.csv").write_text("project_id,project_name\n" + "".join(f"{i},{n}\n" for i, n in projects_rows))
    (folder / "overlaps.csv").write_text("overlap_id,rank\nOVL_1,1\n")
    (folder / "briefs.csv").write_text("overlap_id\nOVL_1\n")


def run_main(monkeypatch, root):
    monkeypatch.setattr(load_db, "ROOT", root)
    monkeypatch.setattr(load_db, "DB_PATH", root / "gridlock.db")
    monkeypatch.setattr(sys, "argv", ["load_db", "--source", "processed"])
    load_db.main()


def test_reload_swaps_the_database_atomically(tmp_path, monkeypatch):
    old = sqlite3.connect(tmp_path / "gridlock.db")
    old.execute("CREATE TABLE projects (project_id TEXT, project_name TEXT)")
    old.execute("INSERT INTO projects VALUES ('OLD', 'old')")
    old.commit()
    old.close()
    write_processed(tmp_path, [("P1", "New one")])
    run_main(monkeypatch, tmp_path)
    rows = sqlite3.connect(tmp_path / "gridlock.db").execute("SELECT project_id FROM projects").fetchall()
    assert rows == [("P1",)]
    assert not (tmp_path / "gridlock.db.tmp").exists()


def test_a_failed_load_keeps_the_old_database_and_removes_the_temp_file(tmp_path, monkeypatch):
    old = sqlite3.connect(tmp_path / "gridlock.db")
    old.execute("CREATE TABLE projects (project_id TEXT)")
    old.execute("INSERT INTO projects VALUES ('OLD')")
    old.commit()
    old.close()
    (tmp_path / "data" / "processed").mkdir(parents=True)          # no CSV files at all
    with pytest.raises(FileNotFoundError):
        run_main(monkeypatch, tmp_path)
    assert sqlite3.connect(tmp_path / "gridlock.db").execute("SELECT project_id FROM projects").fetchall() == [("OLD",)]
    assert not (tmp_path / "gridlock.db.tmp").exists()
```

Create `gridlock/api/tests/test_rebuild.py`:

```python
import sys
import time

from api.rebuild import Rebuilder, default_commands


def wait_for(rebuilder, job_ids, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        states = [rebuilder.status(j)["status"] for j in job_ids]
        if all(s in ("done", "failed") for s in states):
            return states
        time.sleep(0.05)
    raise AssertionError(f"jobs did not finish: {[rebuilder.status(j) for j in job_ids]}")


def script(code):
    return [sys.executable, "-c", code]


def test_successful_rebuild_runs_every_command_in_order(tmp_path):
    log = tmp_path / "log.txt"
    commands = [script(f"open({str(log)!r}, 'a').write('1')"), script(f"open({str(log)!r}, 'a').write('2')")]
    rebuilder = Rebuilder(commands, cwd=tmp_path)
    job = rebuilder.request()
    assert wait_for(rebuilder, [job]) == ["done"]
    assert log.read_text() == "12"


def test_failure_reports_the_error_and_stops_the_chain(tmp_path):
    log = tmp_path / "log.txt"
    commands = [script("import sys; sys.stderr.write('boom: no cache'); sys.exit(3)"), script(f"open({str(log)!r}, 'a').write('x')")]
    rebuilder = Rebuilder(commands, cwd=tmp_path)
    job = rebuilder.request()
    assert wait_for(rebuilder, [job]) == ["failed"]
    assert "boom: no cache" in rebuilder.status(job)["message"]
    assert not log.exists()


def test_a_failed_rebuild_can_be_retried(tmp_path):
    flag = tmp_path / "flag"
    rebuilder = Rebuilder([script(f"import os, sys; sys.exit(0 if os.path.exists({str(flag)!r}) else 1)")], cwd=tmp_path)
    first = rebuilder.request()
    assert wait_for(rebuilder, [first]) == ["failed"]
    flag.write_text("ok")
    second = rebuilder.request()
    assert wait_for(rebuilder, [second]) == ["done"]


def test_requests_during_a_run_are_coalesced_into_one_follow_up(tmp_path):
    log = tmp_path / "log.txt"
    rebuilder = Rebuilder([script(f"import time; open({str(log)!r}, 'a').write('x'); time.sleep(0.5)")], cwd=tmp_path)
    jobs = [rebuilder.request()]
    time.sleep(0.15)                                  # the first run has started
    jobs += [rebuilder.request() for _ in range(4)]   # all arrive while it is running
    assert wait_for(rebuilder, jobs) == ["done"] * 5
    assert log.read_text() == "xx"                    # one run, plus exactly one follow-up


def test_unknown_job_and_default_commands():
    assert Rebuilder([script("pass")]).status("nope") is None
    commands = default_commands()
    assert [c[-1] for c in commands][-1] == "processed" and "pipeline.build_raw" in commands[0]
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest gridlock/api/tests -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'api.rebuild'`, and `load_db` writes in place).

- [ ] **Step 3: Implement**

In `gridlock/api/load_db.py` add `import os` next to the other imports and replace `main()` with:

```python
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["fixtures", "processed"], default="fixtures")
    args = parser.parse_args()

    source_dir = ROOT / "data" / args.source
    # Build the new database beside the live one and swap it in, so readers never see half-loaded tables.
    tmp_path = DB_PATH.with_name(DB_PATH.name + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            with conn:
                load_csv(conn, "projects", source_dir / "projects.csv")
                load_csv(conn, "overlaps", source_dir / "overlaps.csv")
                load_csv(conn, "briefs", source_dir / "briefs.csv")
        finally:
            conn.close()
        os.replace(tmp_path, DB_PATH)
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    print(f"Loaded {args.source} CSVs into {DB_PATH}")
```

Create `gridlock/api/rebuild.py`:

```python
"""Background rebuild worker: build_raw -> run_all -> load_db, one run at a time."""
from __future__ import annotations

import subprocess
import sys
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def default_commands():
    python = sys.executable
    return [
        [python, "-m", "pipeline.build_raw"],
        [python, "geo/run_all.py"],
        [python, "api/load_db.py", "--source", "processed"],
    ]


class Rebuilder:
    def __init__(self, commands=None, cwd=ROOT, timeout=900):
        self.commands = commands if commands is not None else default_commands()
        self.cwd = cwd
        self.timeout = timeout
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._queue: list[str] = []
        self._running = False

    def request(self) -> str:
        """Queue a rebuild and return its job id at once. Jobs queued during a run share one follow-up run."""
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {"status": "queued", "message": ""}
            self._queue.append(job_id)
            if not self._running:
                self._running = True
                threading.Thread(target=self._work, daemon=True).start()
        return job_id

    def status(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def _work(self):
        while True:
            with self._lock:
                batch, self._queue = self._queue, []
                if not batch:
                    self._running = False
                    return
                for job_id in batch:
                    self._jobs[job_id]["status"] = "running"
            ok, message = self._run()
            with self._lock:
                for job_id in batch:
                    self._jobs[job_id].update(status="done" if ok else "failed", message=message)

    def _run(self):
        for command in self.commands:
            try:
                result = subprocess.run(command, cwd=self.cwd, capture_output=True, text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                return False, f"Timed out after {self.timeout} seconds: {' '.join(command[-2:])}"
            except OSError as error:
                return False, f"Could not start {command[0]}: {error}"
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()[-500:]
                return False, f"{' '.join(command[-2:])} failed (exit {result.returncode}): {detail}"
        return True, ""
```

- [ ] **Step 4: Run to verify they pass**

Run: `venv/bin/python -m pytest gridlock/api/tests -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add gridlock/api
git commit -m "Atomic database swap and a coalescing background rebuild worker"
```

---

### Task 7: The submissions API

**Files:**
- Create: `gridlock/api/submissions.py`
- Modify: `gridlock/api/main.py` (mount the router)
- Modify: `requirements.txt` (add `httpx`)
- Test: `gridlock/api/tests/test_submissions_api.py`

**Interfaces:**
- Consumes: `read_pdf`, `SubmissionError`, `FileTooLarge`, `UTILITY_NAMES`, `MAX_BYTES` (Task 2); `prepare_form`, `validate_submission`, `clean_row`, `diff`, `append_submissions`, `set_status`, `history` (Task 3); `Rebuilder` (Task 6).
- Produces (HTTP):
  - `POST /submissions/preview/pdf` (multipart `utility`, `file`) and `POST /submissions/preview/form` (JSON) return `{"utility", "origin", "rows": [{"row", "status", "changes", "errors"}]}` where `status` is `new|update|unchanged|invalid`
  - `POST /submissions/commit` body `{"utility", "origin": "pdf"|"form", "submitted_by", "rows": [row, ...]}` returns `{"saved": [ids], "skipped": [{"project_id","reason"}], "job_id"}`; 422 with `{"message", "skipped"}` if nothing can be saved
  - `GET /submissions/jobs/{job_id}`, `GET /submissions`, `POST /submissions/{id}/reject`, `POST /submissions/{id}/restore`, `POST /submissions/rebuild`
- Module state: `submissions.SUBMISSIONS_PATH`, `submissions.RAW_PROJECTS_PATH`, `submissions.rebuilder` (tests replace these).

- [ ] **Step 1: Write the failing tests**

Create `gridlock/api/tests/test_submissions_api.py`:

```python
import csv
import threading

import pymupdf
import pytest
from fastapi.testclient import TestClient

from api import submissions
from api.main import app
from pipeline.common import RAW_COLUMNS

DESC_PAGE = """Project 43 of 44
Dominion Energy South Carolina
5 Year Budget
Urquhart - Aiken PSA 46 kV: Rebuild
Project ID
6810 O
Project Description
Rebuilding the section of 46 kV line. 4.5 miles.
Project Need
System hardening
Project Status
Planned
Planned In-Service Date
12/31/2027
Estimated Project Cost
Previous
2024
2025
2026
2027
2028
Total*
$0
$0
$0
$0
$3,000,000
$0
$3,000,000
"""

FORM = {"utility": "GPC", "project_name": "Okatie - Bluffton 115kV: Rebuild", "endpoint_a": "Okatie",
        "endpoint_b": "Bluffton", "voltage_kv": "115", "in_service_date": "2026-06-01"}


class FakeRebuilder:
    def __init__(self):
        self.requests = 0

    def request(self):
        self.requests += 1
        return f"job-{self.requests}"

    def status(self, job_id):
        return {"status": "done", "message": ""} if job_id.startswith("job-") else None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(submissions, "SUBMISSIONS_PATH", tmp_path / "submissions.csv")
    monkeypatch.setattr(submissions, "RAW_PROJECTS_PATH", tmp_path / "projects_raw.csv")
    monkeypatch.setattr(submissions, "rebuilder", FakeRebuilder())
    return TestClient(app)


def make_pdf(text):
    doc = pymupdf.open()
    doc.new_page().insert_text((36, 40), text, fontsize=7)
    data = doc.tobytes()
    doc.close()
    return data


def write_current(path, **row):
    base = dict.fromkeys(RAW_COLUMNS, "")
    base.update(project_id="DESC_6810O", utility="DESC", state="SC", project_name="Urquhart - Aiken PSA 46 kV: Rebuild",
                endpoint_a="Urquhart", endpoint_b="Aiken PSA", voltage_kv="46", project_type="rebuild",
                length_mi="4.5", est_cost_usd="3000000", in_service_date="2027-12-31",
                build_start="2027-01-01", build_end="2027-12-31", origin="report")
    base.update(row)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_COLUMNS)
        writer.writeheader()
        writer.writerow(base)


def post_pdf(client, data, utility="DESC", name="r.pdf"):
    return client.post("/submissions/preview/pdf", data={"utility": utility}, files={"file": (name, data, "application/pdf")})


# ---- preview ----------------------------------------------------------------------------

def test_pdf_preview_marks_a_new_project(client):
    response = post_pdf(client, make_pdf(DESC_PAGE))
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "pdf" and body["rows"][0]["status"] == "new"
    assert body["rows"][0]["row"]["project_id"] == "DESC_6810O" and body["rows"][0]["errors"] == []


def test_pdf_preview_marks_an_update_with_its_changes(client, tmp_path):
    write_current(tmp_path / "projects_raw.csv", in_service_date="2026-06-30")
    entry = post_pdf(client, make_pdf(DESC_PAGE)).json()["rows"][0]
    assert entry["status"] == "update"
    assert entry["changes"]["in_service_date"] == ["2026-06-30", "2027-12-31"]


def test_pdf_preview_marks_an_identical_project_unchanged(client, tmp_path):
    write_current(tmp_path / "projects_raw.csv")
    entry = post_pdf(client, make_pdf(DESC_PAGE)).json()["rows"][0]
    assert entry["status"] == "unchanged"


@pytest.mark.parametrize("data,utility,status,fragment", [
    (b"just text", "DESC", 422, "not a PDF"),
    (b"%PDF-1.4 broken", "DESC", 422, "could not be opened"),
    (make_pdf(DESC_PAGE), "GPC", 422, "Dominion Energy SC PDF"),
    (make_pdf(DESC_PAGE), "XYZ", 422, "Choose"),
])
def test_bad_uploads_get_a_plain_message_not_a_500(client, data, utility, status, fragment):
    response = post_pdf(client, data, utility)
    assert response.status_code == status and fragment in response.json()["detail"]


def test_oversized_upload_is_413(client, monkeypatch):
    from pipeline import pdf_submission
    monkeypatch.setattr(pdf_submission, "MAX_BYTES", 50)
    monkeypatch.setattr(submissions, "MAX_BYTES", 50)
    assert post_pdf(client, make_pdf(DESC_PAGE)).status_code == 413


def test_form_preview_new_and_invalid(client):
    ok = client.post("/submissions/preview/form", json=FORM).json()
    assert ok["origin"] == "form" and ok["rows"][0]["status"] == "new" and ok["rows"][0]["row"]["project_id"] == "GPC_SUB1"
    bad = client.post("/submissions/preview/form", json={**FORM, "in_service_date": "13/45/2026"}).json()
    assert bad["rows"][0]["status"] == "invalid" and any("in_service_date" in e for e in bad["rows"][0]["errors"])
    assert client.post("/submissions/preview/form", json={**FORM, "utility": "XYZ"}).status_code == 422


# ---- commit -------------------------------------------------------------------------------

def commit_body(client, **over):
    row = client.post("/submissions/preview/form", json=FORM).json()["rows"][0]["row"]
    return {"utility": "GPC", "origin": "form", "submitted_by": "Ana", "rows": [row], **over}


def test_commit_saves_rows_starts_a_rebuild_and_labels_the_company(client):
    response = client.post("/submissions/commit", json=commit_body(client))
    assert response.status_code == 200
    body = response.json()
    assert len(body["saved"]) == 1 and body["job_id"] == "job-1" and body["skipped"] == []
    history = client.get("/submissions").json()
    assert history[0]["project_id"] == "GPC_SUB1" and history[0]["status"] == "active"
    assert history[0]["submitted_by"] == "Georgia Power (Ana)"
    assert client.get(f"/submissions/jobs/{body['job_id']}").json()["status"] == "done"


def test_commit_ignores_forged_status_and_ids(client):
    body = commit_body(client)
    body["rows"][0].update(status="rejected", submission_id="sub_evil", submitted_at="1999")
    client.post("/submissions/commit", json=body)
    saved = client.get("/submissions").json()[0]
    assert saved["status"] == "active" and saved["submission_id"] != "sub_evil"


def test_commit_revalidates_and_skips_bad_rows(client):
    body = commit_body(client)
    body["rows"].append({**body["rows"][0], "project_id": "GPC_2", "in_service_date": "not a date"})
    response = client.post("/submissions/commit", json=body)
    assert response.status_code == 200
    assert [s["project_id"] for s in response.json()["skipped"]] == ["GPC_2"]


def test_commit_rejects_duplicates_within_one_request_and_wrong_utility(client):
    body = commit_body(client)
    body["rows"].append(dict(body["rows"][0]))
    skipped = client.post("/submissions/commit", json=body).json()["skipped"]
    assert len(skipped) == 1 and "duplicate" in skipped[0]["reason"]
    wrong = commit_body(client, utility="DESC")
    response = client.post("/submissions/commit", json=wrong)
    assert response.status_code == 422 and "GPC" in response.json()["detail"]["skipped"][0]["reason"]


def test_commit_of_unchanged_or_empty_is_a_422_that_saves_nothing(client, tmp_path):
    write_current(tmp_path / "projects_raw.csv")
    row = post_pdf(client, make_pdf(DESC_PAGE)).json()["rows"][0]["row"]
    response = client.post("/submissions/commit", json={"utility": "DESC", "origin": "pdf", "submitted_by": "", "rows": [row]})
    assert response.status_code == 422 and response.json()["detail"]["skipped"][0]["reason"] == "unchanged"
    assert client.get("/submissions").json() == []
    assert submissions.rebuilder.requests == 0


def test_concurrent_commits_lose_nothing(client):
    results = []

    def go(n):
        own = TestClient(app)                              # one client per thread
        row = own.post("/submissions/preview/form", json={**FORM, "utility_project_id": f"C{n}"}).json()["rows"][0]["row"]
        results.append(own.post("/submissions/commit", json={"utility": "GPC", "origin": "form", "submitted_by": "", "rows": [row]}).status_code)

    threads = [threading.Thread(target=go, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == [200] * 6 and len(client.get("/submissions").json()) == 6


# ---- history, reject / restore, jobs -------------------------------------------------------

def test_reject_and_restore_are_reversible_and_start_rebuilds(client):
    client.post("/submissions/commit", json=commit_body(client))
    submission_id = client.get("/submissions").json()[0]["submission_id"]
    rejected = client.post(f"/submissions/{submission_id}/reject").json()
    assert rejected["status"] == "rejected" and rejected["job_id"]
    assert client.get("/submissions").json()[0]["status"] == "rejected"
    restored = client.post(f"/submissions/{submission_id}/restore").json()
    assert restored["status"] == "active"
    assert client.post("/submissions/sub_missing/reject").status_code == 404


def test_jobs_and_manual_rebuild(client):
    assert client.get("/submissions/jobs/unknown").status_code == 404
    job = client.post("/submissions/rebuild").json()["job_id"]
    assert client.get(f"/submissions/jobs/{job}").json() == {"status": "done", "message": ""}
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python -m pytest gridlock/api/tests/test_submissions_api.py -q`
Expected: FAIL (`ImportError: cannot import name 'submissions' from 'api'`).

- [ ] **Step 3: Implement**

Add `httpx` to `requirements.txt` (one line at the end).

Create `gridlock/api/submissions.py`:

```python
"""Company submissions: preview a PDF or form, commit confirmed rows, manage history."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from api.rebuild import Rebuilder
from pipeline.pdf_submission import MAX_BYTES, UTILITY_NAMES, FileTooLarge, SubmissionError, read_pdf
from pipeline.submission_store import (
    append_submissions, clean_row, diff, history, prepare_form, set_status, validate_submission,
)

ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS_PATH = ROOT / "data" / "interim" / "submissions.csv"
RAW_PROJECTS_PATH = ROOT / "data" / "interim" / "projects_raw.csv"
rebuilder = Rebuilder()

router = APIRouter(prefix="/submissions", tags=["submissions"])


def _utility(value: str) -> str:
    utility = (value or "").strip().upper()
    if utility not in UTILITY_NAMES:
        raise HTTPException(status_code=422, detail="Choose Georgia Power or Dominion Energy SC.")
    return utility


def _current_by_id() -> dict[str, dict]:
    if not RAW_PROJECTS_PATH.exists():
        return {}
    with RAW_PROJECTS_PATH.open(newline="", encoding="utf-8") as handle:
        return {row["project_id"]: row for row in csv.DictReader(handle)}


def _entry(row: dict, errors: list[str], current: dict) -> dict:
    info = {"status": "invalid", "changes": {}} if errors else diff(row, current)
    return {"row": row, "status": info["status"], "changes": info["changes"], "errors": errors}


@router.post("/preview/pdf")
async def preview_pdf(utility: str = Form(...), file: UploadFile = File(...)) -> dict:
    utility = _utility(utility)
    data = await file.read(MAX_BYTES + 1)
    try:
        rows = read_pdf(data, utility, file.filename or "upload.pdf")
    except FileTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except SubmissionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    current, seen, entries = _current_by_id(), set(), []
    for row in rows:
        errors = validate_submission(row)
        if row["project_id"] in seen:
            errors.append("duplicate project_id within this PDF")
        seen.add(row["project_id"])
        entries.append(_entry(row, errors, current))
    return {"utility": utility, "origin": "pdf", "filename": file.filename, "rows": entries}


@router.post("/preview/form")
def preview_form(payload: dict) -> dict:
    current = _current_by_id()
    row, errors = prepare_form(payload, taken_ids=set(current))
    if not row:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    return {"utility": row["utility"], "origin": "form", "rows": [_entry(row, errors, current)]}


class CommitBody(BaseModel):
    utility: str
    origin: Literal["pdf", "form"]
    submitted_by: str = ""
    rows: list[dict]


@router.post("/commit")
def commit(body: CommitBody) -> dict:
    utility = _utility(body.utility)
    current, seen, to_save, skipped = _current_by_id(), set(), [], []
    for raw in body.rows:
        row = clean_row(raw)
        project_id = row["project_id"]
        errors = validate_submission(row)
        if row["utility"] != utility:
            errors.append(f"utility: row is {row['utility']!r} but the submission is for {utility}")
        if project_id in seen:
            errors.append("duplicate project_id within this submission")
        seen.add(project_id)
        if errors:
            skipped.append({"project_id": project_id, "reason": "; ".join(errors)})
            continue
        if diff(row, current)["status"] == "unchanged":
            skipped.append({"project_id": project_id, "reason": "unchanged"})
            continue
        to_save.append(row)
    if not to_save:
        raise HTTPException(status_code=422, detail={"message": "Nothing to save.", "skipped": skipped})
    company = UTILITY_NAMES[utility]
    note = " ".join(body.submitted_by.split())
    ids = append_submissions(to_save, body.origin, f"{company} ({note})" if note else company, SUBMISSIONS_PATH)
    return {"saved": ids, "skipped": skipped, "job_id": rebuilder.request()}


@router.get("/jobs/{job_id}")
def job(job_id: str) -> dict:
    status = rebuilder.status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return status


@router.post("/rebuild")
def rebuild() -> dict:
    return {"job_id": rebuilder.request()}


@router.get("")
def list_history() -> list[dict]:
    keep = ("submission_id", "project_id", "project_name", "utility", "origin", "submitted_by",
            "submitted_at", "status", "in_service_date")
    return [{key: row[key] for key in keep} for row in history(SUBMISSIONS_PATH)]


def _change(submission_id: str, status: str) -> dict:
    try:
        set_status(submission_id, status, SUBMISSIONS_PATH)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Unknown submission") from error
    return {"submission_id": submission_id, "status": status, "job_id": rebuilder.request()}


@router.post("/{submission_id}/reject")
def reject(submission_id: str) -> dict:
    return _change(submission_id, "rejected")


@router.post("/{submission_id}/restore")
def restore(submission_id: str) -> dict:
    return _change(submission_id, "active")
```

In `gridlock/api/main.py`, add after the `from pydantic import BaseModel` import:

```python
from api.submissions import router as submissions_router
```

and after the CORS `app.add_middleware(...)` block:

```python
app.include_router(submissions_router)
```

- [ ] **Step 4: Run to verify they pass**

Run: `venv/bin/python -m pytest gridlock -q`
Expected: all PASS. Also confirm the server still imports the way the team runs it:

```bash
venv/bin/python -c "import sys; sys.path.insert(0, 'gridlock'); import api.main; print(len(api.main.app.routes), 'routes')"
```
Expected: prints a route count without an import error.

- [ ] **Step 5: Commit**

```bash
git add gridlock/api requirements.txt
git commit -m "Add submissions API: preview, commit, history, reject/restore, rebuild jobs"
```

---

### Task 8: Frontend dialog, helpers and map marker

**Files:**
- Create: `gridlock/web/submit-helpers.js`, `gridlock/web/submit.js`
- Create: `gridlock/web/tests/submit-helpers.test.js`
- Modify: `gridlock/web/index.html`, `gridlock/web/styles.css`, `gridlock/web/main.js`

**Interfaces:**
- Consumes: the API from Task 7; the global `API` constant from `main.js`.
- Produces (pure helpers, browser globals and `module.exports`): `buildFormPayload(values, utility, submittedBy)`, `statusBadge(status)`, `describeChanges(changes)`, `selectableIndexes(entries)`, `jobMessage(job)`, `errorText(payload)`.

- [ ] **Step 1: Write the failing tests**

Create `gridlock/web/tests/submit-helpers.test.js`:

```js
const test = require("node:test");
const assert = require("node:assert");
const h = require("../submit-helpers.js");

test("buildFormPayload trims values, keeps only known fields and adds company and note", () => {
  const payload = h.buildFormPayload({ project_name: "  Okatie - Bluffton ", voltage_kv: " 115 ", junk: "x", lat_a: "" }, "GPC", " Ana ");
  assert.deepStrictEqual(payload, { utility: "GPC", submitted_by: "Ana", project_name: "Okatie - Bluffton", voltage_kv: "115" });
});

test("statusBadge labels every status and falls back safely", () => {
  assert.strictEqual(h.statusBadge("new").label, "New");
  assert.strictEqual(h.statusBadge("update").label, "Update");
  assert.strictEqual(h.statusBadge("unchanged").label, "Unchanged");
  assert.strictEqual(h.statusBadge("invalid").label, "Invalid");
  assert.strictEqual(h.statusBadge("weird").label, "weird");
});

test("describeChanges lists old to new per field", () => {
  assert.strictEqual(h.describeChanges({ in_service_date: ["2024-12-31", "2025-06-01"], voltage_kv: ["", "115"] }),
    "in_service_date: 2024-12-31 \u2192 2025-06-01; voltage_kv: (empty) \u2192 115");
  assert.strictEqual(h.describeChanges({}), "");
});

test("selectableIndexes returns only new or update rows without errors", () => {
  const entries = [
    { status: "new", errors: [] }, { status: "unchanged", errors: [] }, { status: "invalid", errors: ["x"] },
    { status: "update", errors: [] }, { status: "new", errors: ["x"] },
  ];
  assert.deepStrictEqual(h.selectableIndexes(entries), [0, 3]);
});

test("jobMessage and errorText produce readable text", () => {
  assert.match(h.jobMessage({ status: "running", message: "" }), /Updating/);
  assert.match(h.jobMessage({ status: "failed", message: "boom" }), /boom/);
  assert.strictEqual(h.jobMessage({ status: "done", message: "" }), "Done. Reloading the map\u2026");
  assert.strictEqual(h.errorText({ detail: "Not a PDF" }), "Not a PDF");
  assert.strictEqual(h.errorText({ detail: { message: "Nothing to save.", skipped: [{ project_id: "GPC_1", reason: "unchanged" }] } }),
    "Nothing to save. GPC_1: unchanged");
  assert.strictEqual(h.errorText(null), "Something went wrong.");
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --test gridlock/web/tests/`
Expected: FAIL (`Cannot find module '../submit-helpers.js'`).

- [ ] **Step 3: Implement the helpers**

Create `gridlock/web/submit-helpers.js`:

```js
const FORM_FIELDS = [
  "utility_project_id", "project_name", "endpoint_a", "endpoint_b", "voltage_kv", "length_mi",
  "est_cost_usd", "build_start", "in_service_date", "lat_a", "lon_a", "lat_b", "lon_b",
];

function buildFormPayload(values, utility, submittedBy) {
  const payload = { utility, submitted_by: String(submittedBy || "").trim() };
  FORM_FIELDS.forEach((field) => {
    const value = String(values[field] ?? "").trim();
    if (value) payload[field] = value;
  });
  return payload;
}

function statusBadge(status) {
  const known = {
    new: { label: "New", className: "badge-new" },
    update: { label: "Update", className: "badge-update" },
    unchanged: { label: "Unchanged", className: "badge-muted" },
    invalid: { label: "Invalid", className: "badge-invalid" },
  };
  return known[status] || { label: String(status), className: "badge-muted" };
}

function describeChanges(changes) {
  return Object.entries(changes || {})
    .map(([field, [oldValue, newValue]]) => `${field}: ${oldValue || "(empty)"} \u2192 ${newValue || "(empty)"}`)
    .join("; ");
}

function selectableIndexes(entries) {
  return entries.flatMap((entry, index) =>
    (entry.status === "new" || entry.status === "update") && !(entry.errors || []).length ? [index] : []);
}

function jobMessage(job) {
  if (job.status === "failed") return `The update failed: ${job.message || "unknown error"}. Your submission is saved; you can retry.`;
  if (job.status === "done") return "Done. Reloading the map\u2026";
  return "Updating the map data (about 10 seconds)\u2026";
}

function errorText(payload) {
  if (!payload || payload.detail === undefined) return "Something went wrong.";
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  const skipped = (detail.skipped || []).map((s) => `${s.project_id}: ${s.reason}`).join("; ");
  return [detail.message, skipped].filter(Boolean).join(" ");
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { FORM_FIELDS, buildFormPayload, statusBadge, describeChanges, selectableIndexes, jobMessage, errorText };
}
```

- [ ] **Step 4: Run to verify the helper tests pass**

Run: `node --test gridlock/web/tests/`
Expected: all PASS.

- [ ] **Step 5: Add the dialog markup, styles and behaviour**

In `gridlock/web/index.html`, inside the sidebar `<header>` after the `<h1>`, add:

```html
          <button id="open-submit" class="submit-open" type="button">Submit a project</button>
```

Before the first `<script>` tag near the bottom, add:

```html
    <dialog id="submit-dialog" class="submit-dialog" aria-labelledby="submit-title">
      <div class="dialog-head">
        <h2 id="submit-title">Submit a project</h2>
        <button id="close-submit" class="dialog-close" type="button" aria-label="Close">&times;</button>
      </div>
      <div class="dialog-tabs" role="tablist">
        <button type="button" data-tab="pdf" class="active">Upload PDF</button>
        <button type="button" data-tab="form">Manual form</button>
        <button type="button" data-tab="history">History</button>
      </div>
      <p id="submit-status" class="submit-status" role="status"></p>

      <section data-panel="pdf">
        <label>Company
          <select id="pdf-utility"><option value="GPC">Georgia Power</option><option value="DESC">Dominion Energy SC</option></select>
        </label>
        <label>PDF in the Georgia Power IRP or Dominion project layout
          <input id="pdf-file" type="file" accept="application/pdf" />
        </label>
        <label>Submitted by (optional)<input id="pdf-by" type="text" maxlength="80" /></label>
        <button id="pdf-preview" type="button">Preview</button>
        <div id="pdf-result"></div>
      </section>

      <section data-panel="form" hidden>
        <form id="project-form" autocomplete="off">
          <label>Company
            <select name="utility"><option value="GPC">Georgia Power</option><option value="DESC">Dominion Energy SC</option></select>
          </label>
          <label>Utility project ID (optional)<input name="utility_project_id" type="text" /></label>
          <label>Project name<input name="project_name" type="text" required /></label>
          <label>Endpoint A (substation)<input name="endpoint_a" type="text" /></label>
          <label>Endpoint B (optional)<input name="endpoint_b" type="text" /></label>
          <label>Voltage (kV)<input name="voltage_kv" type="text" inputmode="numeric" /></label>
          <label>Length (miles)<input name="length_mi" type="text" inputmode="decimal" /></label>
          <label>Estimated cost (USD)<input name="est_cost_usd" type="text" inputmode="numeric" /></label>
          <label>Build start (optional)<input name="build_start" type="date" /></label>
          <label>In-service date<input name="in_service_date" type="date" required /></label>
          <fieldset><legend>Optional coordinates (latitude, then longitude)</legend>
            <label>A latitude<input name="lat_a" type="text" inputmode="decimal" /></label>
            <label>A longitude<input name="lon_a" type="text" inputmode="decimal" /></label>
            <label>B latitude<input name="lat_b" type="text" inputmode="decimal" /></label>
            <label>B longitude<input name="lon_b" type="text" inputmode="decimal" /></label>
          </fieldset>
          <label>Submitted by (optional)<input name="submitted_by" type="text" maxlength="80" /></label>
          <button id="form-preview" type="submit">Preview</button>
        </form>
        <div id="form-result"></div>
      </section>

      <section data-panel="history" hidden>
        <div id="history-list"></div>
      </section>
    </dialog>
```

and add these two script tags after `main.js`:

```html
    <script src="./submit-helpers.js"></script>
    <script src="./submit.js"></script>
```

Append to `gridlock/web/styles.css`:

```css
.submit-open {
  margin-top: 10px;
  padding: 9px 14px;
  border: 1px solid var(--overlap);
  border-radius: 8px;
  background: var(--overlap);
  color: #fff;
  font-weight: 800;
  cursor: pointer;
}

.submit-dialog {
  width: min(760px, calc(100vw - 32px));
  max-height: calc(100vh - 48px);
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: auto;
}

.submit-dialog::backdrop { background: rgba(23, 32, 38, 0.45); }
.submit-dialog section, .submit-dialog .dialog-head, .submit-dialog .dialog-tabs, .submit-status { padding: 12px 20px; }
.dialog-head { display: flex; justify-content: space-between; align-items: center; }
.dialog-head h2 { margin: 0; }
.dialog-close { border: 0; background: transparent; font-size: 1.6rem; cursor: pointer; }
.dialog-tabs { display: flex; gap: 8px; border-bottom: 1px solid var(--line); }
.dialog-tabs button { padding: 8px 12px; border: 1px solid var(--line); border-radius: 8px; background: #fff; font-weight: 800; cursor: pointer; }
.dialog-tabs button.active { background: #effaf4; color: var(--overlap); border-color: var(--overlap); }
.submit-dialog label { display: block; margin: 8px 0; font-size: 0.85rem; font-weight: 700; }
.submit-dialog input, .submit-dialog select { display: block; width: 100%; margin-top: 4px; padding: 8px; box-sizing: border-box; }
.submit-dialog fieldset { margin: 10px 0; border: 1px solid var(--line); border-radius: 8px; }
.submit-status { min-height: 1.2em; margin: 0; color: var(--muted); font-weight: 700; }
.submit-status.error { color: #b3261e; }
.submit-table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 0.82rem; }
.submit-table th, .submit-table td { padding: 6px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-weight: 800; font-size: 0.72rem; }
.badge-new { background: #e6f6ec; color: #17603a; }
.badge-update { background: #fff4d6; color: #7a5600; }
.badge-muted { background: #eef1f3; color: #4f616c; }
.badge-invalid { background: #fde7e5; color: #b3261e; }
.row-errors { color: #b3261e; }
.submit-dialog button.primary { margin-top: 8px; padding: 9px 14px; border: 0; border-radius: 8px; background: var(--overlap); color: #fff; font-weight: 800; cursor: pointer; }
```

Create `gridlock/web/submit.js`:

```js
const submitState = { preview: null };

function submitEl(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  });
  [].concat(children).forEach((child) => node.append(child));
  return node;
}

function setSubmitStatus(message, isError = false) {
  const status = document.querySelector("#submit-status");
  status.textContent = message;
  status.classList.toggle("error", isError);
}

async function submitJson(url, options) {
  const response = await fetch(url, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch {}
  if (!response.ok) throw new Error(errorText(payload));
  return payload;
}

function renderPreview(container, preview) {
  submitState.preview = preview;
  container.replaceChildren();
  const selectable = new Set(selectableIndexes(preview.rows));
  const table = submitEl("table", { class: "submit-table" }, [
    submitEl("tr", {}, ["", "Status", "Project", "Endpoints", "In service", "Details"].map((h) => submitEl("th", {}, h))),
  ]);
  preview.rows.forEach((entry, index) => {
    const badge = statusBadge(entry.status);
    const checkbox = submitEl("input", { type: "checkbox", "data-index": String(index) });
    checkbox.checked = selectable.has(index);
    checkbox.disabled = !selectable.has(index);
    const details = entry.errors.length
      ? submitEl("span", { class: "row-errors" }, entry.errors.join("; "))
      : document.createTextNode(describeChanges(entry.changes));
    table.append(submitEl("tr", {}, [
      submitEl("td", {}, checkbox),
      submitEl("td", {}, submitEl("span", { class: `badge ${badge.className}` }, badge.label)),
      submitEl("td", {}, `${entry.row.project_id}: ${entry.row.project_name}`),
      submitEl("td", {}, [entry.row.endpoint_a, entry.row.endpoint_b].filter(Boolean).join(" \u2013 ")),
      submitEl("td", {}, entry.row.in_service_date),
      submitEl("td", {}, details),
    ]));
  });
  container.append(table);
  if (selectable.size) {
    const confirm = submitEl("button", { type: "button", class: "primary" }, "Confirm and add to the map");
    confirm.addEventListener("click", () => commitPreview(container));
    container.append(confirm);
  } else {
    container.append(submitEl("p", {}, "Nothing here can be added. Fix the errors or change the file."));
  }
}

async function previewPdf() {
  const file = document.querySelector("#pdf-file").files[0];
  if (!file) return setSubmitStatus("Choose a PDF first.", true);
  const body = new FormData();
  body.append("utility", document.querySelector("#pdf-utility").value);
  body.append("file", file);
  setSubmitStatus("Reading the PDF\u2026");
  try {
    const preview = await submitJson(`${API}/submissions/preview/pdf`, { method: "POST", body });
    renderPreview(document.querySelector("#pdf-result"), { ...preview, submitted_by: document.querySelector("#pdf-by").value });
    setSubmitStatus(`${preview.rows.length} project(s) found. Review and confirm.`);
  } catch (error) {
    document.querySelector("#pdf-result").replaceChildren();
    setSubmitStatus(error.message, true);
  }
}

async function previewForm(event) {
  event.preventDefault();
  const form = document.querySelector("#project-form");
  const values = Object.fromEntries(new FormData(form).entries());
  const payload = buildFormPayload(values, values.utility, values.submitted_by);
  setSubmitStatus("Checking\u2026");
  try {
    const preview = await submitJson(`${API}/submissions/preview/form`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    renderPreview(document.querySelector("#form-result"), { ...preview, submitted_by: values.submitted_by });
    setSubmitStatus("Review and confirm.");
  } catch (error) {
    document.querySelector("#form-result").replaceChildren();
    setSubmitStatus(error.message, true);
  }
}

async function commitPreview(container) {
  const preview = submitState.preview;
  const chosen = [...container.querySelectorAll("input[type=checkbox]:checked")].map((box) => preview.rows[Number(box.dataset.index)].row);
  if (!chosen.length) return setSubmitStatus("Tick at least one row.", true);
  container.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    const result = await submitJson(`${API}/submissions/commit`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ utility: preview.utility, origin: preview.origin, submitted_by: preview.submitted_by || "", rows: chosen }),
    });
    const skipped = result.skipped.length ? ` (${result.skipped.length} skipped)` : "";
    setSubmitStatus(`Saved ${result.saved.length} project(s)${skipped}. ${jobMessage({ status: "running" })}`);
    await pollJob(result.job_id);
  } catch (error) {
    container.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    setSubmitStatus(error.message, true);
  }
}

async function pollJob(jobId) {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const job = await submitJson(`${API}/submissions/jobs/${jobId}`);
    if (job.status === "done") {
      setSubmitStatus(jobMessage(job));
      setTimeout(() => window.location.reload(), 600);
      return;
    }
    if (job.status === "failed") {
      setSubmitStatus(jobMessage(job), true);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  setSubmitStatus("The update is taking longer than expected. Check History and try again.", true);
}

async function loadHistory() {
  const list = document.querySelector("#history-list");
  list.replaceChildren(submitEl("p", {}, "Loading\u2026"));
  try {
    const rows = await submitJson(`${API}/submissions`);
    list.replaceChildren();
    if (!rows.length) return list.append(submitEl("p", {}, "No submissions yet."));
    const table = submitEl("table", { class: "submit-table" }, [
      submitEl("tr", {}, ["When", "Project", "By", "Status", ""].map((h) => submitEl("th", {}, h))),
    ]);
    rows.forEach((row) => {
      const rejected = row.status === "rejected";
      const button = submitEl("button", { type: "button" }, rejected ? "Restore" : "Reject");
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const result = await submitJson(`${API}/submissions/${row.submission_id}/${rejected ? "restore" : "reject"}`, { method: "POST" });
          setSubmitStatus(`${rejected ? "Restored" : "Rejected"}. ${jobMessage({ status: "running" })}`);
          await pollJob(result.job_id);
        } catch (error) {
          button.disabled = false;
          setSubmitStatus(error.message, true);
        }
      });
      table.append(submitEl("tr", {}, [
        submitEl("td", {}, row.submitted_at.slice(0, 16).replace("T", " ")),
        submitEl("td", {}, `${row.project_id}: ${row.project_name}`),
        submitEl("td", {}, `${row.submitted_by} (${row.origin})`),
        submitEl("td", {}, row.status),
        submitEl("td", {}, button),
      ]));
    });
    list.append(table);
  } catch (error) {
    list.replaceChildren();
    setSubmitStatus(error.message, true);
  }
}

function initSubmitDialog() {
  const dialog = document.querySelector("#submit-dialog");
  document.querySelector("#open-submit").addEventListener("click", () => { setSubmitStatus(""); dialog.showModal(); });
  document.querySelector("#close-submit").addEventListener("click", () => dialog.close());
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("[data-tab]").forEach((other) => other.classList.toggle("active", other === tab));
      document.querySelectorAll("[data-panel]").forEach((panel) => { panel.hidden = panel.dataset.panel !== tab.dataset.tab; });
      setSubmitStatus("");
      if (tab.dataset.tab === "history") loadHistory();
    });
  });
  document.querySelector("#pdf-preview").addEventListener("click", previewPdf);
  document.querySelector("#project-form").addEventListener("submit", previewForm);
}

initSubmitDialog();
```

- [ ] **Step 6: Map marker for submitted projects**

In `gridlock/web/main.js`:

1. In `projectLineFeatures()`, add `origin: project.origin || "report",` to the feature `properties` object.
2. In `addMapSourcesAndLayers()`, immediately after the `map.addLayer({ id: "project-lines", ... })` call and before the `overlap-lines` source is added, add:

```js
  map.addLayer({
    id: "project-lines-submitted",
    type: "line",
    source: "project-lines",
    filter: ["!=", ["get", "origin"], "report"],
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": 2, "line-dasharray": [1.5, 1.5], "line-opacity": 0.95 },
  });
```

3. Add this helper next to `updateProjectVisibility`, and replace the three `map.setFilter("project-lines", X)` calls inside `updateProjectVisibility` with `setProjectFilter(X)`:

```js
function setProjectFilter(filter) {
  map.setFilter("project-lines", filter);
  if (map.getLayer("project-lines-submitted")) {
    const submitted = ["!=", ["get", "origin"], "report"];
    map.setFilter("project-lines-submitted", filter ? ["all", submitted, filter] : submitted);
  }
}
```

4. In the project popup (`bindMapLayerEvents`), add this line inside the popup HTML template, before `Source: ${props.source_ref}`:

```js
        ${props.origin && props.origin !== "report" ? "<em>Submitted by the company \u00b7 unverified</em><br>" : ""}
```

- [ ] **Step 7: Verify**

Run: `node --check gridlock/web/main.js && node --check gridlock/web/submit.js && node --test gridlock/web/tests/`
Expected: no syntax errors; helper tests PASS.

Then run the app and try it for real (this needs a Mapbox token; the dialog itself does not):

```bash
venv/bin/python -m uvicorn api.main:app --app-dir gridlock --port 8000
```
(second terminal) `venv/bin/python -m http.server 5173 --directory gridlock/web`, then open `http://localhost:5173/?token=pk.YOUR_TOKEN`, click **Submit a project**, and confirm: the dialog opens; a bad file shows a plain error; a Dominion page shows a preview row with a New badge; the manual form previews and shows field errors. Stop before confirming anything so no test data is written.

- [ ] **Step 8: Commit**

```bash
git add gridlock/web
git commit -m "Add the submission dialog, helpers and a dashed marker for submitted projects"
```

---

### Task 9: End-to-end test, docs and repository hygiene

**Files:**
- Create: `gridlock/api/tests/test_submissions_e2e.py`
- Modify: `.gitignore`, `md_artifacts/00_TEAM_CONTRACT.md`

- [ ] **Step 1: Write the end-to-end test**

Create `gridlock/api/tests/test_submissions_e2e.py`:

```python
"""preview -> commit -> merge -> projects_raw, with the rebuild run in-process."""
import csv

import pymupdf
import pytest
from fastapi.testclient import TestClient

from api import submissions
from api.main import app
from pipeline import build_raw
from pipeline.common import COLUMNS

DESC_PAGE = """Project 43 of 44
Dominion Energy South Carolina
5 Year Budget
Urquhart - Aiken PSA 46 kV: Rebuild
Project ID
6810 O
Project Description
Rebuilding the section of 46 kV line. 4.5 miles.
Project Need
System hardening
Project Status
Planned
Planned In-Service Date
06/30/2028
Estimated Project Cost
Previous
2024
2025
2026
2027
2028
Total*
$0
$0
$0
$0
$0
$3,000,000
$3,000,000
"""


class InProcessRebuilder:
    def __init__(self, baseline, submissions_path, out):
        self.baseline, self.submissions_path, self.out = baseline, submissions_path, out
        self.count = 0

    def request(self):
        rows = build_raw.build(raw=self.out.parent / "no-report-text", baseline=self.baseline, submissions=self.submissions_path)
        build_raw.write(rows, self.out)
        self.count += 1
        return f"job-{self.count}"

    def status(self, job_id):
        return {"status": "done", "message": ""}


def read_out(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["project_id"]: row for row in csv.DictReader(handle)}


@pytest.fixture
def world(tmp_path, monkeypatch):
    baseline = tmp_path / "projects_report.csv"
    row = dict.fromkeys(COLUMNS, "")
    row.update(project_id="DESC_6810O", utility="DESC", state="SC", project_name="Urquhart - Aiken PSA 46 kV: Rebuild",
               endpoint_a="Urquhart", endpoint_b="Aiken PSA", voltage_kv="46", project_type="rebuild", length_mi="4.5",
               est_cost_usd="3000000", in_service_date="2027-12-31", build_start="2027-01-01", build_end="2027-12-31")
    with baseline.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    out, log = tmp_path / "projects_raw.csv", tmp_path / "submissions.csv"
    rebuilder = InProcessRebuilder(baseline, log, out)
    rebuilder.request()                                    # the state before any submission
    monkeypatch.setattr(submissions, "SUBMISSIONS_PATH", log)
    monkeypatch.setattr(submissions, "RAW_PROJECTS_PATH", out)
    monkeypatch.setattr(submissions, "rebuilder", rebuilder)
    return TestClient(app), out


def pdf_bytes():
    doc = pymupdf.open()
    doc.new_page().insert_text((36, 40), DESC_PAGE, fontsize=7)
    data = doc.tobytes()
    doc.close()
    return data


def test_pdf_update_then_reject_restores_the_report_value(world):
    client, out = world
    assert read_out(out)["DESC_6810O"]["in_service_date"] == "2027-12-31"
    preview = client.post("/submissions/preview/pdf", data={"utility": "DESC"}, files={"file": ("r.pdf", pdf_bytes(), "application/pdf")}).json()
    assert preview["rows"][0]["status"] == "update"
    body = {"utility": "DESC", "origin": "pdf", "submitted_by": "Ana", "rows": [preview["rows"][0]["row"]]}
    assert client.post("/submissions/commit", json=body).status_code == 200

    row = read_out(out)["DESC_6810O"]
    assert row["in_service_date"] == "2028-06-30" and row["origin"] == "pdf" and row["project_name"].startswith("Urquhart")
    assert row["est_cost_usd"] == "3000000" and row["submitted_by"] == "Dominion Energy SC (Ana)"

    again = client.post("/submissions/preview/pdf", data={"utility": "DESC"}, files={"file": ("r.pdf", pdf_bytes(), "application/pdf")}).json()
    assert again["rows"][0]["status"] == "unchanged"                       # double submit is harmless
    assert client.post("/submissions/commit", json={**body, "rows": [again["rows"][0]["row"]]}).status_code == 422

    submission_id = client.get("/submissions").json()[0]["submission_id"]
    client.post(f"/submissions/{submission_id}/reject")
    restored = read_out(out)["DESC_6810O"]
    assert restored["in_service_date"] == "2027-12-31" and restored["origin"] == "report"


def test_manual_form_adds_a_new_project_with_its_coordinates(world):
    client, out = world
    form = {"utility": "GPC", "project_name": "Okatie - Bluffton 115kV: Rebuild", "endpoint_a": "Okatie",
            "endpoint_b": "Bluffton", "in_service_date": "2029-03-01", "lat_a": "32.2776", "lon_a": "-80.9686"}
    entry = client.post("/submissions/preview/form", json=form).json()["rows"][0]
    assert entry["status"] == "new" and entry["errors"] == []
    client.post("/submissions/commit", json={"utility": "GPC", "origin": "form", "submitted_by": "", "rows": [entry["row"]]})
    row = read_out(out)["GPC_SUB1"]
    assert row["origin"] == "form" and row["state"] == "GA" and row["given_lat_a"] == "32.2776"
    assert row["build_start"] == "2029-01-01" and row["build_end"] == "2029-03-01"
```

- [ ] **Step 2: Run to verify**

Run: `venv/bin/python -m pytest gridlock/api/tests/test_submissions_e2e.py -q`
Expected: PASS. If `test_pdf_update_then_reject_restores_the_report_value` fails on the `in_service_date`, print the preview row before changing anything: the Dominion sample date is `06/30/2028`, so the merged value must be `2028-06-30`.

- [ ] **Step 3: Repository hygiene and docs**

Append to `.gitignore`:

```
gridlock/data/interim/submissions.csv
gridlock/data/interim/submissions.csv.lock
gridlock/data/submissions/
```

In `md_artifacts/00_TEAM_CONTRACT.md`, add a new section `## Submissions (companies add or update projects)` after the API contract table, containing exactly:

```markdown
## Submissions (companies add or update projects)

A company can upload a PDF (Georgia Power IRP layout or Dominion project page layout) or fill a form. Submissions live in `data/interim/submissions.csv` (append-only revisions, gitignored runtime state). `pipeline/build_raw.py` lays the latest active submission per `project_id` over `data/interim/projects_report.csv` (the committed baseline of parsed report rows) to write `projects_raw.csv`.

**New `projects_raw.csv` columns** (after the 16 contract columns): `origin` (`report`, `pdf` or `form`), `submission_id`, `submitted_by`, `submitted_at`, `given_lat_a`, `given_lon_a`, `given_lat_b`, `given_lon_b` (optional coordinates that skip name matching for that endpoint). These flow through to `projects.csv`.

**Rules:** blank submitted fields keep the existing value; only valid, changed rows are saved; unverified submissions are capped at confidence 0.6 (`medium`) until `manual_fixes.csv` verifies them; rejecting a submission restores the previous values.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/submissions/preview/pdf` | multipart `utility`, `file`; returns rows with `status` (`new`, `update`, `unchanged`, `invalid`), `changes`, `errors` |
| `POST` | `/submissions/preview/form` | JSON form fields; same response |
| `POST` | `/submissions/commit` | `{utility, origin, submitted_by, rows}`; saves valid changed rows and starts a rebuild; returns `saved`, `skipped`, `job_id` |
| `GET` | `/submissions/jobs/{job_id}` | `queued`, `running`, `done`, `failed` with a message |
| `GET` | `/submissions` | history, newest first |
| `POST` | `/submissions/{id}/reject` and `/restore` | reversible; each starts a rebuild |
| `POST` | `/submissions/rebuild` | retry after a failed rebuild |

A rebuild runs `python -m pipeline.build_raw`, `python geo/run_all.py`, then `python api/load_db.py --source processed` from `gridlock/`. `run_all.py` needs the cached OSM data; without the power-line cache it skips routes and endpoint inference and says so.
```

- [ ] **Step 4: Full verification**

Run:
```bash
venv/bin/python -m pytest gridlock -q
node --test gridlock/web/tests/
PYTHONPATH=gridlock venv/bin/python -m pipeline.build_raw
git status --short
```
Expected: all tests PASS; `contract violations: 0`; `git status` shows only intended files (no `submissions.csv`, no `.lock`, no `.tmp`).

Then one real run through the geo pipeline with a throwaway submission, to prove the pieces connect (this writes `submissions.csv`, which is gitignored; delete it afterwards):

```bash
venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, "gridlock")
from pipeline.submission_store import prepare_form, append_submissions
row, errors = prepare_form({"utility": "DESC", "project_name": "Test Tap - Sample 115kV: Construct", "endpoint_a": "Bluffton", "in_service_date": "2027-05-01"})
assert not errors, errors
append_submissions([row], "form", "smoke test")
EOF
PYTHONPATH=gridlock venv/bin/python -m pipeline.build_raw && venv/bin/python gridlock/geo/run_all.py | head -3 && grep -c "DESC_SUB1" gridlock/data/processed/projects.csv
rm gridlock/data/interim/submissions.csv gridlock/data/interim/submissions.csv.lock
PYTHONPATH=gridlock venv/bin/python -m pipeline.build_raw && venv/bin/python gridlock/geo/run_all.py > /dev/null
git status --short gridlock/data
```
Expected: the `grep -c` prints `1` (the submission reached `projects.csv`), and after the cleanup `git status --short gridlock/data` shows nothing. If it does show modified files, run `git diff --stat gridlock/data` and look at what changed before doing anything; do not discard changes blindly.

- [ ] **Step 5: Commit**

```bash
git add gridlock/api/tests/test_submissions_e2e.py .gitignore md_artifacts/00_TEAM_CONTRACT.md
git commit -m "Add submissions end-to-end test and document the contract"
```

---

## Self-review notes

- **Spec coverage:** PDF reader (Task 2); store, validation, diff, merge, history, undo (Task 3); pipeline merge and new columns (Task 4); given coordinates and confidence cap (Task 5); atomic database swap (Task 6); rebuild worker and job status (Task 6); API endpoints including reject, restore and manual rebuild (Task 7); dialog with PDF, form and history tabs, Submitted badge and dashed line (Task 8); contract updates and the baseline paragraph the spec was missing (Task 9). Out-of-scope items (logins, cell editing, other layouts, map pins) have no tasks.
- **Type consistency:** `prepare_form`, `validate_submission`, `clean_row`, `diff`, `merge_rows`, `append_submissions`, `set_status`, `history` keep the same signatures in Tasks 3, 4, 7 and 9. `Rebuilder.request/status` match between Tasks 6, 7 and the fakes. `ROW_KEYS`/`GIVEN` are used only inside `submission_store`.
- **Known dependency:** Task 4's regenerated `projects_raw.csv` and processed CSVs change tracked data files; commit them in that task so later tasks start from a green state.
