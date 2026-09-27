from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "gridlock.db"
MANUAL_FIXES = ROOT / "data" / "processed" / "manual_fixes.csv"

app = FastAPI(title="Gridlock Radar API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProjectPatch(BaseModel):
    lat_center: float
    lon_center: float
    human_verified: bool = True


def db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(status_code=500, detail="gridlock.db not found. Run api/load_db.py first.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with db() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def row(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    result = rows(sql, params)
    return result[0] if result else None


@app.get("/projects")
def get_projects(utility: str | None = None, min_confidence: float | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM projects WHERE 1=1"
    params: list[Any] = []
    if utility:
        sql += " AND utility = ?"
        params.append(utility)
    if min_confidence is not None:
        sql += " AND CAST(COALESCE(NULLIF(confidence, ''), '0') AS REAL) >= ?"
        params.append(min_confidence)
    sql += " ORDER BY utility, project_id"
    return rows(sql, tuple(params))


@app.get("/routes")
def get_routes() -> dict[str, Any]:
    path = ROOT / "data" / "processed" / "routes.geojson"
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/overlaps")
def get_overlaps(limit: int = Query(20, ge=1, le=200)) -> list[dict[str, Any]]:
    overlaps = rows("SELECT * FROM overlaps ORDER BY CAST(rank AS INTEGER) LIMIT ?", (limit,))
    return [inflate_overlap(overlap) for overlap in overlaps]


@app.get("/overlaps/{overlap_id}")
def get_overlap(overlap_id: str) -> dict[str, Any]:
    overlap = row("SELECT * FROM overlaps WHERE overlap_id = ?", (overlap_id,))
    if not overlap:
        raise HTTPException(status_code=404, detail="Overlap not found")
    inflated = inflate_overlap(overlap)
    inflated["brief"] = row("SELECT * FROM briefs WHERE overlap_id = ?", (overlap_id,))
    return inflated


@app.get("/briefs/{overlap_id}")
def get_brief(overlap_id: str, shared_mi: float = 5, cost_per_acre: int = 10000) -> dict[str, Any]:
    overlap = row("SELECT * FROM overlaps WHERE overlap_id = ?", (overlap_id,))
    if not overlap:
        raise HTTPException(status_code=404, detail="Overlap not found")
    row_width_ft = 100
    shared_acres = shared_mi * row_width_ft / 8.25
    savings = round(shared_acres * cost_per_acre)
    return {
        "overlap_id": overlap_id,
        "shared_corridor_mi": shared_mi,
        "row_width_ft": row_width_ft,
        "shared_acres": round(shared_acres, 2),
        "land_cost_per_acre_usd": cost_per_acre,
        "est_land_savings_usd": savings,
        "assumptions_note": "Fixture estimate assumes one shared right-of-way corridor and 100 ft width.",
    }


@app.post("/briefs/{overlap_id}/narrative")
def post_narrative(overlap_id: str) -> dict[str, str]:
    overlap = get_overlap(overlap_id)
    narrative = (
        f"{overlap_id} is a coordination opportunity because the two projects are "
        f"{overlap['distance_mi']} miles apart with a {overlap['time_gap_days']} day timing gap. "
        "The estimate is directional and depends on the shared corridor and land cost assumptions."
    )
    return {"overlap_id": overlap_id, "narrative": narrative}


@app.patch("/projects/{project_id}")
def patch_project(project_id: str, patch: ProjectPatch) -> dict[str, Any]:
    with db() as conn:
        cur = conn.execute(
            "UPDATE projects SET lat_center = ?, lon_center = ?, human_verified = ? WHERE project_id = ?",
            (patch.lat_center, patch.lon_center, str(patch.human_verified).lower(), project_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Project not found")

    MANUAL_FIXES.parent.mkdir(parents=True, exist_ok=True)
    exists = MANUAL_FIXES.exists()
    with MANUAL_FIXES.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["project_id", "lat_center", "lon_center", "human_verified"])
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "project_id": project_id,
                "lat_center": patch.lat_center,
                "lon_center": patch.lon_center,
                "human_verified": str(patch.human_verified).lower(),
            }
        )
    return row("SELECT * FROM projects WHERE project_id = ?", (project_id,))


def inflate_overlap(overlap: dict[str, Any]) -> dict[str, Any]:
    overlap = dict(overlap)
    overlap["gpc"] = row("SELECT * FROM projects WHERE project_id = ?", (overlap["project_id_gpc"],))
    overlap["desc"] = row("SELECT * FROM projects WHERE project_id = ?", (overlap["project_id_desc"],))
    return overlap
