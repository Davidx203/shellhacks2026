"""Build the three processed CSVs from Luis's raw projects and cached OSM data."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

from confidence import apply_route_evidence, score_project
from cost import make_brief
from geocode import CACHE, border_distance_mi, fetch_substations, geocode_project
from rank import rank_overlaps
from routes import PowerGrid, attach_routes, fetch_power_lines


DATA = Path(__file__).resolve().parents[1] / "data"
RAW = DATA / "interim" / "projects_raw.csv"
PROCESSED = DATA / "processed"
PROJECT_EXTRA = ["lat_a", "lon_a", "lat_b", "lon_b", "lat_center", "lon_center", "osm_id_a", "osm_id_b", "confidence", "confidence_tier", "human_verified", "route_mi"]
OVERLAP_COLUMNS = ["overlap_id", "project_id_gpc", "project_id_desc", "distance_mi", "band", "time_gap_days", "windows_overlap", "overlap_days", "window_gap_days", "voltage_match", "score", "rank"]
BRIEF_COLUMNS = ["overlap_id", "shared_corridor_mi", "row_width_ft", "shared_acres", "land_cost_per_acre_usd", "est_land_savings_usd", "assumptions_note"]


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def apply_manual_fixes(projects: list[dict], path: Path) -> None:
    if not path.exists():
        return
    _, fixes = read_csv(path)
    latest = {fix["project_id"]: fix for fix in fixes}
    for project in projects:
        fix = latest.get(project["project_id"])
        if not fix or fix.get("human_verified", "").lower() != "true":
            continue
        project["lat_center"] = float(fix["lat_center"])
        project["lon_center"] = float(fix["lon_center"])
        project["human_verified"] = "true"
        project["confidence"] = 1.0
        project["confidence_tier"] = "high"


def review_distance(project: dict) -> float:
    if project["lat_center"] == "":
        return math.inf
    return border_distance_mi(float(project["lat_center"]), float(project["lon_center"]))


def build(raw: Path = RAW, output: Path = PROCESSED, cache: Path = CACHE) -> tuple[list[dict], list[dict], list[dict]]:
    columns, raw_projects = read_csv(raw)
    features = fetch_substations(cache)
    projects = []
    for item in raw_projects:
        located, matches = geocode_project(item, features)
        projects.append(score_project(located, matches))
    ways = fetch_power_lines()
    if ways:
        route_features = attach_routes(projects, PowerGrid(ways))
        for project in projects:
            apply_route_evidence(project)
        (output / "routes.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": route_features}), encoding="utf-8")
        print(f"Routes along power lines: {len(route_features)}")
    else:
        for project in projects:
            project["route_mi"] = ""
        print("Power-line data unavailable; skipped routes (routes.geojson left as is)")
    apply_manual_fixes(projects, output / "manual_fixes.csv")
    routes_path = output / "routes.geojson"
    routes = {}
    if routes_path.exists():
        for feature in json.loads(routes_path.read_text(encoding="utf-8"))["features"]:
            routes[feature["properties"]["project_id"]] = [(lat, lon) for lon, lat in feature["geometry"]["coordinates"]]
    overlaps = rank_overlaps(projects, routes)
    lookup = {p["project_id"]: p for p in projects}
    briefs = [make_brief(pair, lookup) for pair in overlaps[:10]]
    write_csv(output / "projects.csv", columns + PROJECT_EXTRA, projects)
    write_csv(output / "overlaps.csv", OVERLAP_COLUMNS, overlaps)
    write_csv(output / "briefs.csv", BRIEF_COLUMNS, briefs)
    review = sorted((p for p in projects if p["confidence_tier"] in {"low", "unmatched"}),
                    key=lambda p: (review_distance(p), p["project_id"]))
    write_csv(output / "geo_review_queue.csv", ["project_id", "utility", "project_name", "endpoint_a", "endpoint_b", "confidence_tier", "lat_center", "lon_center", "border_distance_mi"],
              [{**{k: p[k] for k in ("project_id", "utility", "project_name", "endpoint_a", "endpoint_b", "confidence_tier", "lat_center", "lon_center")},
                "border_distance_mi": "" if math.isinf(review_distance(p)) else round(review_distance(p), 1)} for p in review])
    print(f"Projects: {len(projects)}; overlaps: {len(overlaps)}; briefs: {len(briefs)}")
    print("By utility and tier:", dict(sorted(Counter((p["utility"], p["confidence_tier"]) for p in projects).items())))
    print("Review queue:", len(review))
    for pair in overlaps[:5]:
        print(f'#{pair["rank"]} {lookup[pair["project_id_gpc"]]["project_name"]} + {lookup[pair["project_id_desc"]]["project_name"]} ({pair["distance_mi"]} mi, score {pair["score"]})')
    return projects, overlaps, briefs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--output", type=Path, default=PROCESSED)
    parser.add_argument("--cache", type=Path, default=CACHE)
    args = parser.parse_args()
    build(args.raw, args.output, args.cache)
