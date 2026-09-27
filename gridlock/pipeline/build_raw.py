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
