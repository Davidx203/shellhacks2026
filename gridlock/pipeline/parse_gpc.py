"""Parse Georgia Power IRP Volume 3 detail blocks."""
import re
from pathlib import Path

from .common import clamp_window, endpoints, iso_date, max_kv

_TEAMS = re.compile(r"^Teams # (\S+)")
_NEED = re.compile(r"Need Date (\S+)")
_START = re.compile(r"Start Date (\S+)")


def parse_text(text, source_file="gpc_irp_vol3.txt"):
    lines = text.split("\n")
    rows = []
    for i, ln in enumerate(lines):
        m = _TEAMS.match(ln.strip())
        if not m:
            continue
        name = lines[i - 1].strip()
        dates = lines[i + 1]
        need, start = _NEED.search(dates), _START.search(dates)
        a, b = endpoints(name)
        start_iso = iso_date(start.group(1)) if start else ""
        need_iso = iso_date(need.group(1)) if need else ""
        build_start, build_end = clamp_window(start_iso, need_iso)
        rows.append({
            "project_id": f"GPC_{m.group(1)}",
            "utility": "GPC",
            "state": "GA",
            "project_name": name,
            "endpoint_a": a,
            "endpoint_b": b,
            "voltage_kv": max_kv(name),
            "project_type": "",
            "length_mi": None,
            "est_cost_usd": None,
            "start_date": start_iso,
            "in_service_date": need_iso,
            "build_start": build_start,
            "build_end": build_end,
            "source_file": source_file,
            "source_ref": f"Teams # {m.group(1)}",
        })
    return rows


def parse_all(path):
    return parse_text(Path(path).read_text(encoding="utf-8"))
