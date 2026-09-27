"""Find nearby projects from Georgia Power and Dominion Energy South Carolina."""

import argparse
import csv
from datetime import date
from math import asin, cos, hypot, radians, sin, sqrt

from timeline import window_relation
from pathlib import Path


DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "projects.csv"
MAX_DISTANCE_MI = 25.0
TOUCH_MI = 0.05
BANDS = [(TOUCH_MI, "crossing"), (1.0, "share_land"), (5.0, "share_logistics"), (MAX_DISTANCE_MI, "share_crews")]
MI_PER_DEG_LAT = 69.0
MI_PER_DEG_LON_AT_EQUATOR = 69.17


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


def band_for(distance_mi):
    """crossing (touching), share_land (~1.6 km), share_logistics (~8 km), share_crews (~40 km)."""
    for limit, name in BANDS:
        if distance_mi <= limit or (name != "crossing" and distance_mi < limit):
            return name
    return None


def project_geometry(project, routes=None):
    """Points (lat, lon) that make up the project: its route, else endpoint A-B, else its center."""
    if project.get("human_verified") == "true":
        center = project_center(project)
        return [center] if center else None
    if routes and project["project_id"] in routes:
        return routes[project["project_id"]]
    if project.get("lat_a") and project.get("lat_b"):
        return [(float(project["lat_a"]), float(project["lon_a"])), (float(project["lat_b"]), float(project["lon_b"]))]
    center = project_center(project)
    return [center] if center else None


def _bbox(points):
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    return min(lats), min(lons), max(lats), max(lons)


def _bbox_gap_mi(a, b):
    lat_gap = max(0.0, max(a[0], b[0]) - min(a[2], b[2])) * MI_PER_DEG_LAT
    mid = (a[0] + a[2] + b[0] + b[2]) / 4
    lon_gap = max(0.0, max(a[1], b[1]) - min(a[3], b[3])) * MI_PER_DEG_LON_AT_EQUATOR * cos(radians(mid))
    return hypot(lat_gap, lon_gap)


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _point_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length))
    return hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _segment_distance(p1, p2, q1, q2):
    d1, d2 = _cross(p1, p2, q1), _cross(p1, p2, q2)
    d3, d4 = _cross(q1, q2, p1), _cross(q1, q2, p2)
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return 0.0
    return min(_point_segment(p1, q1, q2), _point_segment(p2, q1, q2),
               _point_segment(q1, p1, p2), _point_segment(q2, p1, p2))


def geometry_distance_miles(a, b):
    """Closest-point distance between two point lists (a single point counts as a degenerate line)."""
    if len(a) == 1 and len(b) == 1:
        return haversine_miles(*a[0], *b[0])
    lat0 = sum(p[0] for p in a + b) / len(a + b)
    kx, ky = MI_PER_DEG_LON_AT_EQUATOR * cos(radians(lat0)), MI_PER_DEG_LAT
    pa, pb = [(p[1] * kx, p[0] * ky) for p in a], [(p[1] * kx, p[0] * ky) for p in b]
    pa = pa if len(pa) > 1 else pa * 2
    pb = pb if len(pb) > 1 else pb * 2
    best = float("inf")
    for p1, p2 in zip(pa, pa[1:]):
        for q1, q2 in zip(pb, pb[1:]):
            best = min(best, _segment_distance(p1, p2, q1, q2))
            if best == 0.0:
                return 0.0
    return best


def find_overlaps(projects, max_distance_mi=MAX_DISTANCE_MI, routes=None):
    """Compare every located GPC project with every located DESC project by closest-point distance."""
    def located(utility):
        items = []
        for p in projects:
            if p["utility"] == utility and (geometry := project_geometry(p, routes)):
                items.append((p, geometry, _bbox(geometry)))
        return items

    overlaps = []
    for gpc_project, gpc_geometry, gpc_box in located("GPC"):
        for desc_project, desc_geometry, desc_box in located("DESC"):
            if _bbox_gap_mi(gpc_box, desc_box) >= max_distance_mi:
                continue
            distance = geometry_distance_miles(gpc_geometry, desc_geometry)
            if distance >= max_distance_mi:
                continue

            gpc_date = gpc_project.get("in_service_date", "")
            desc_date = desc_project.get("in_service_date", "")
            time_gap_days = (
                abs((date.fromisoformat(gpc_date) - date.fromisoformat(desc_date)).days)
                if gpc_date and desc_date else None
            )
            window = window_relation(gpc_project, desc_project)
            overlaps.append({
                "project_id_gpc": gpc_project["project_id"],
                "project_id_desc": desc_project["project_id"],
                "distance_mi": round(distance, 2),
                "band": band_for(distance),
                "time_gap_days": time_gap_days,
                "windows_overlap": window["windows_overlap"],
                "overlap_days": window["overlap_days"],
                "window_gap_days": window["window_gap_days"],
                "shorter_window_days": window["shorter_days"],
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
