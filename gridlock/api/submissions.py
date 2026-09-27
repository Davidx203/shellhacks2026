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
    clean_row, commit_rows, current_by_id, diff, history, prepare_form, reserved_ids, set_status, validate_submission,
)

ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS_PATH = ROOT / "data" / "interim" / "submissions.csv"
BASELINE_PATH = ROOT / "data" / "interim" / "projects_report.csv"
rebuilder = Rebuilder()

router = APIRouter(prefix="/submissions", tags=["submissions"])


def _utility(value: str) -> str:
    utility = (value or "").strip().upper()
    if utility not in UTILITY_NAMES:
        raise HTTPException(status_code=422, detail="Choose Georgia Power or Dominion Energy SC.")
    return utility


def _baseline_rows() -> list[dict]:
    if not BASELINE_PATH.exists():
        return []
    with BASELINE_PATH.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _current_by_id() -> dict[str, dict]:
    """The report baseline with every active submission laid over it: the truth, not the last rebuild's output."""
    return current_by_id(_baseline_rows(), SUBMISSIONS_PATH)


SUMMARY_FIELDS = ("project_id", "project_name", "endpoint_a", "endpoint_b", "in_service_date")


def _entry(row: dict, errors: list[str], current: dict) -> dict:
    info = {"status": "invalid", "changes": {}} if errors else diff(row, current)
    filled = {key: value for key, value in row.items() if value not in ("", None)}
    merged = {**current.get(row.get("project_id"), {}), **filled}       # what the table should show
    return {"row": row, "status": info["status"], "changes": info["changes"], "errors": errors,
            "summary": {key: merged.get(key, "") for key in SUMMARY_FIELDS}}


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
    row, errors = prepare_form(payload, taken_ids=reserved_ids(_baseline_rows(), SUBMISSIONS_PATH), current_by_id=current)
    if not row:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    return {"utility": row["utility"], "origin": "form", "rows": [_entry(row, errors, current)]}


class CommitBody(BaseModel):
    utility: str
    origin: Literal["pdf", "form"]
    submitted_by: str = ""
    rows: list[dict]
    expected: dict[str, str] = {}      # project_id -> the status the submitter saw in the preview


@router.post("/commit")
def commit(body: CommitBody) -> dict:
    utility = _utility(body.utility)
    seen, valid, skipped = set(), [], []
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
        else:
            valid.append(row)
    company = UTILITY_NAMES[utility]
    note = " ".join(body.submitted_by.split())
    ids, not_saved = commit_rows(valid, body.origin, f"{company} ({note})" if note else company,
                                 _baseline_rows(), expected=body.expected, path=SUBMISSIONS_PATH)
    skipped += not_saved
    if not ids:
        raise HTTPException(status_code=422, detail={"message": "Nothing to save.", "skipped": skipped})
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
