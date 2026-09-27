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


_NUMBER = re.compile(r"\$?\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:kv|mi|miles?)?", re.I)


def _number(value):
    """A plain number as people write it ($3,000,000; 8.7 mi; 115 kV), or None. Anything ambiguous is None."""
    match = _NUMBER.fullmatch(str(value if value is not None else "").strip())
    return float(match.group(1).replace(",", "")) if match else None


def _numeric_field(payload, key, whole, errors):
    raw = _text(payload.get(key))
    if not raw:
        return ""
    number = _number(raw)
    if number is None:
        errors.append(f"{key}: {raw!r} is not a plain number (use digits, optionally with commas or a decimal point)")
        return ""
    if whole:
        return str(int(round(number)))
    return str(int(number)) if number == int(number) else str(number)


def _voltage_field(payload, errors):
    raw = _text(payload.get("voltage_kv"))
    if not raw:
        return ""
    number = None if raw.startswith("-") else _number(raw)
    if number is not None:
        return str(int(round(number)))
    found = None if raw.startswith("-") else max_kv(raw if "kv" in raw.lower() else raw + " kV")
    if found:
        return str(found)                     # e.g. 230/115 kV -> 230, the highest voltage mentioned
    errors.append(f"voltage_kv: {raw!r} is not a voltage (for example 115 or 230 kV)")
    return ""


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
    if _text(payload.get("voltage_kv")):
        voltage = _voltage_field(payload, errors)
    else:
        voltage = str(max_kv(name)) if max_kv(name) else ""

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


TEXT_FIELDS = ("project_name", "endpoint_a", "endpoint_b", "source_file", "source_ref")
NAME_FIELDS = ("project_name", "endpoint_a", "endpoint_b")
FORMULA_PREFIXES = ("=", "+", "@", "-", "\t", "\r")


def _text_errors(row):
    errors = []
    for key in TEXT_FIELDS:
        value = str(row.get(key) or "")
        if value[:1] in FORMULA_PREFIXES or value.lstrip()[:1] in FORMULA_PREFIXES:
            errors.append(f"{key}: must not start with {value.lstrip()[:1]!r}")
        if len(value) > 200:
            errors.append(f"{key}: longer than 200 characters")
        if "<" in value or ">" in value:
            errors.append(f"{key}: '<' and '>' are not allowed")
    source = str(row.get("source_file") or "")
    if source != "form" and not source.startswith("submission:"):
        errors.append(f"source_file: {source!r} is not a submission source")
    return errors


def validate_submission(row):
    """Every problem that would stop this row being saved, as plain messages."""
    errors = [m.split(": ", 1)[1] if ": " in m else m for m in validate([row])]
    errors += _text_errors(row)
    if not row.get("endpoint_a"):
        errors.append("endpoint_a: give at least one substation name")
    project_id, utility = str(row.get("project_id") or ""), str(row.get("utility") or "")
    if utility not in STATE or not re.fullmatch(rf"{re.escape(utility)}_[\w.,\-]+", project_id):
        errors.append(f"project_id: {project_id!r} must start with {utility or 'the company'}_ and use only letters, digits and . , _ -")
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
