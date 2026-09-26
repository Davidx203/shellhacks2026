from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "Sperry-Tech-Challenge" / "Projects_Overlaps.xlsx"
OUT_DIR = ROOT / "data" / "fixtures"

NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

PROJECT_COLUMNS = [
    "project_id",
    "utility",
    "state",
    "project_name",
    "endpoint_a",
    "endpoint_b",
    "voltage_kv",
    "project_type",
    "length_mi",
    "est_cost_usd",
    "start_date",
    "in_service_date",
    "source_file",
    "source_ref",
    "lat_a",
    "lon_a",
    "lat_b",
    "lon_b",
    "lat_center",
    "lon_center",
    "osm_id_a",
    "osm_id_b",
    "confidence",
    "confidence_tier",
    "human_verified",
]

OVERLAP_COLUMNS = [
    "overlap_id",
    "project_id_gpc",
    "project_id_desc",
    "distance_mi",
    "time_gap_days",
    "voltage_match",
    "score",
    "rank",
]


def shared_strings(zf: ZipFile) -> list[str]:
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("a:si", NS):
        values.append("".join(t.text or "" for t in item.findall(".//a:t", NS)))
    return values


def sheet_rows(zf: ZipFile, sheet_name: str, strings: list[str]) -> list[dict[str, str]]:
    sheet_path = {"projects": "xl/worksheets/sheet1.xml", "overlaps": "xl/worksheets/sheet2.xml"}[sheet_name]
    root = ET.fromstring(zf.read(sheet_path))
    rows: list[list[str]] = []
    for row in root.findall(".//a:row", NS):
        values: dict[int, str] = {}
        for cell in row.findall("a:c", NS):
            ref = cell.attrib.get("r", "A1")
            col = column_index(ref)
            value = cell.find("a:v", NS)
            text = "" if value is None else value.text or ""
            if cell.attrib.get("t") == "s" and text:
                text = strings[int(text)]
            values[col] = text
        if values:
            rows.append([values.get(i, "") for i in range(max(values) + 1)])

    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


def column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref).group(0)
    total = 0
    for char in letters:
        total = total * 26 + ord(char) - ord("A") + 1
    return total - 1


def utility_code(value: str) -> str:
    return {
        "Georgia Power": "GPC",
        "Dominion Energy South Carolina": "DESC",
        "GPC": "GPC",
        "DESC": "DESC",
    }.get(value, value)


def iso_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.isdigit():
        base = datetime(1899, 12, 30)
        return (base + timedelta(days=int(value))).date().isoformat()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return value


def voltage(project_name: str) -> str:
    nums = [int(n) for n in re.findall(r"(\d{2,3})\s*KV", project_name.upper())]
    return str(max(nums)) if nums else ""


def project_type(project_name: str) -> str:
    name = project_name.lower()
    if "rebuild" in name:
        return "rebuild"
    if "reconductor" in name:
        return "reconductor"
    if "construct" in name or "new" in name:
        return "new_line"
    if "sub" in name:
        return "substation"
    if "relay" in name:
        return "relay"
    return "other"


def make_projects(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    projects = []
    for row in rows:
        item = {col: "" for col in PROJECT_COLUMNS}
        item.update(
            {
                "project_id": row.get("project_id", ""),
                "utility": utility_code(row.get("utility", "")),
                "state": row.get("state", ""),
                "project_name": row.get("project_name", ""),
                "endpoint_a": row.get("name_a", ""),
                "endpoint_b": row.get("name_b", ""),
                "voltage_kv": voltage(row.get("project_name", "")),
                "project_type": project_type(row.get("project_name", "")),
                "in_service_date": iso_date(row.get("in_service_date", "")),
                "source_file": "Projects_Overlaps.xlsx",
                "source_ref": row.get("project_id", ""),
                "lat_a": row.get("lat_a", ""),
                "lon_a": row.get("lon_a", ""),
                "lat_b": row.get("lat_b", ""),
                "lon_b": row.get("lon_b", ""),
                "lat_center": row.get("lat_center", ""),
                "lon_center": row.get("lon_center", ""),
                "confidence": "1.0",
                "confidence_tier": "high",
                "human_verified": "true",
            }
        )
        projects.append(item)
    return projects


def make_overlaps(rows: list[dict[str, str]], projects: list[dict[str, str]]) -> list[dict[str, str]]:
    by_id = {p["project_id"]: p for p in projects}
    overlaps = []
    for index, row in enumerate(rows, start=1):
        a = row.get("project_id_a", "")
        b = row.get("project_id_b", "")
        gpc = a if a.startswith("GPC") else b
        desc = a if a.startswith("DESC") else b
        gpc_project = by_id.get(gpc, {})
        desc_project = by_id.get(desc, {})
        voltage_match = bool(gpc_project and desc_project and gpc_project.get("voltage_kv") == desc_project.get("voltage_kv"))
        distance = float(row.get("distance_mi") or 0)
        score = max(0.0, round(1 - distance / 25, 3))
        overlaps.append(
            {
                "overlap_id": row.get("overlap_id", f"OVL_{index}"),
                "project_id_gpc": gpc,
                "project_id_desc": desc,
                "distance_mi": row.get("distance_mi", ""),
                "time_gap_days": row.get("time_gap (day)", ""),
                "voltage_match": str(voltage_match).lower(),
                "score": str(score),
                "rank": str(index),
            }
        )
    return overlaps


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    with ZipFile(WORKBOOK) as zf:
        strings = shared_strings(zf)
        project_rows = sheet_rows(zf, "projects", strings)
        overlap_rows = sheet_rows(zf, "overlaps", strings)

    projects = make_projects(project_rows)
    overlaps = make_overlaps(overlap_rows, projects)
    write_csv(OUT_DIR / "projects.csv", PROJECT_COLUMNS, projects)
    write_csv(OUT_DIR / "overlaps.csv", OVERLAP_COLUMNS, overlaps)
    print(f"Wrote {len(projects)} projects and {len(overlaps)} overlaps to {OUT_DIR}")


if __name__ == "__main__":
    main()
