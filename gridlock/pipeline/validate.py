"""Contract checks for projects_raw.csv rows (list of dicts as read by csv.DictReader)."""
import re
from datetime import datetime

from .common import RAW_COLUMNS

TYPES = {"new_line", "rebuild", "reconductor", "substation", "relay", "other"}
STATE = {"GPC": "GA", "DESC": "SC"}
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate(rows, columns=None):
    errs = []
    if columns is not None and list(columns) != RAW_COLUMNS:
        errs.append(f"columns differ from contract: {columns}")
    seen = set()
    for r in rows:
        pid = r.get("project_id", "?")
        if pid in seen:
            errs.append(f"{pid}: duplicate project_id")
        seen.add(pid)
        if r.get("utility") not in STATE:
            errs.append(f"{pid}: bad utility {r.get('utility')!r}")
        elif r.get("state") != STATE[r["utility"]]:
            errs.append(f"{pid}: state {r.get('state')!r} does not match utility")
        if not r.get("project_name"):
            errs.append(f"{pid}: blank project_name")
        if r.get("project_type") not in TYPES:
            errs.append(f"{pid}: bad project_type {r.get('project_type')!r}")
        for col in ("start_date", "in_service_date", "build_start", "build_end"):
            v = r.get(col, "")
            if v and not _ISO.match(str(v)):
                errs.append(f"{pid}: {col} not ISO: {v!r}")
            elif v:
                try:
                    datetime.strptime(str(v), "%Y-%m-%d")
                except ValueError:
                    errs.append(f"{pid}: {col} is not a real date: {v!r}")
        if r.get("build_start") and r.get("build_end") and r["build_start"] > r["build_end"]:
            errs.append(f"{pid}: build_start after build_end")
        if not r.get("in_service_date"):
            errs.append(f"{pid}: blank in_service_date")
        for col in ("voltage_kv", "est_cost_usd"):
            v = str(r.get(col, "") or "")
            if v and not re.fullmatch(r"\d+", v):
                errs.append(f"{pid}: {col} not an integer: {v!r}")
        v = str(r.get("length_mi", "") or "")
        if v and not re.fullmatch(r"\d+(\.\d+)?", v):
            errs.append(f"{pid}: length_mi not a number: {v!r}")
    return errs
