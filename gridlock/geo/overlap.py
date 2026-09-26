"""Find nearby projects from Georgia Power and Dominion Energy South Carolina."""

import argparse
import csv
from datetime import date
from math import asin, cos, radians, sin, sqrt
from pathlib import Path


DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "projects.csv"
MAX_DISTANCE_MI = 25.0


def haversine_miles(lat1, lon1, lat2, lon2):
    radius_mi = 3958.8
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius_mi * asin(sqrt(a))


def project_center(project):
    """Return the geocoded center, or None when no location is available."""
    lat, lon = project.get("lat_center", ""), project.get("lon_center", "")
    if lat and lon:
        return float(lat), float(lon)
    return None


def find_overlaps(projects, max_distance_mi=MAX_DISTANCE_MI):
    """Compare every located GPC project with every located DESC project."""
    gpc = [p for p in projects if p["utility"] == "GPC" and project_center(p)]
    desc = [p for p in projects if p["utility"] == "DESC" and project_center(p)]
    overlaps = []

    for gpc_project in gpc:
        for desc_project in desc:
            distance = haversine_miles(*project_center(gpc_project), *project_center(desc_project))
            if distance >= max_distance_mi:
                continue

            gpc_date = gpc_project.get("in_service_date", "")
            desc_date = desc_project.get("in_service_date", "")
            time_gap_days = (
                abs((date.fromisoformat(gpc_date) - date.fromisoformat(desc_date)).days)
                if gpc_date and desc_date else None
            )
            overlaps.append({
                "project_id_gpc": gpc_project["project_id"],
                "project_id_desc": desc_project["project_id"],
                "distance_mi": round(distance, 2),
                "time_gap_days": time_gap_days,
                "voltage_match": bool(gpc_project.get("voltage_kv"))
                and gpc_project.get("voltage_kv") == desc_project.get("voltage_kv"),
            })

    return sorted(overlaps, key=lambda pair: pair["distance_mi"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Geocoded projects CSV")
    args = parser.parse_args()

    with args.input.open(newline="", encoding="utf-8-sig") as source:
        projects = list(csv.DictReader(source))

    if not {"lat_center", "lon_center"}.issubset(projects[0] if projects else {}):
        parser.error("input needs lat_center and lon_center columns; geocode projects_raw.csv first")

    overlaps = find_overlaps(projects)
    for pair in overlaps:
        print(f"{pair['project_id_gpc']} + {pair['project_id_desc']}: "
              f"{pair['distance_mi']:.2f} mi, "
              f"time gap {pair['time_gap_days']} days")
    print(f"Found {len(overlaps)} pairs under {MAX_DISTANCE_MI:g} miles.")


if __name__ == "__main__":
    main()
