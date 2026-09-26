"""Build data/interim/projects_raw.csv from both utilities."""
import csv
import sys
from collections import Counter
from pathlib import Path

from .classify import classify
from .common import COLUMNS
from .parse_desc import parse_all as parse_desc_all
from .validate import validate

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "interim" / "projects_raw.csv"


def build():
    rows = parse_desc_all(RAW / "desc_pages")
    gpc = RAW / "gpc_irp_vol3.txt"
    try:
        from .parse_gpc import parse_all as parse_gpc_all
        rows += parse_gpc_all(gpc)
    except ImportError:
        print("parse_gpc not available yet: DESC only", file=sys.stderr)
    for r in rows:
        r["project_type"] = classify(r["project_name"])
        if r["project_type"] == "relay":
            r["endpoint_b"] = ""
    return rows


def write(rows, out=OUT):
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="raise")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r[k] is None else r[k]) for k in COLUMNS})


def report(rows):
    lines = [f"rows: {len(rows)}"]
    lines.append("by utility: " + str(dict(Counter(r["utility"] for r in rows))))
    lines.append("by type: " + str(dict(Counter(r["project_type"] for r in rows))))
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
