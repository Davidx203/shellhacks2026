"""Score and rank cross-utility project overlaps."""

import argparse
import csv
from pathlib import Path

from overlap import find_overlaps


DEFAULT_PROJECTS = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "projects.csv"
DISTANCE_WEIGHT = 0.60
TIME_WEIGHT = 0.35
VOLTAGE_WEIGHT = 0.05
MAX_DISTANCE_MI = 25.0
OVERLAP_BASE = 0.7
WINDOW_FADE_DAYS = 1095
DISTANCE_CURVE = 0.7
CONFIDENCE_FLOOR = 0.75
PARTIAL_LOCATION_FACTOR = 0.85


def distance_score(distance_mi):
    """Concave: nearness is rewarded more than a straight line would (3 mi ~0.91, 12.5 mi ~0.62, 25 mi 0)."""
    return max(0.0, 1 - distance_mi / MAX_DISTANCE_MI) ** DISTANCE_CURVE


def effective_confidence(project):
    """How far to trust a project's location for ranking.

    A two-endpoint project with only one endpoint located is not penalised as if the missing
    endpoint were a failed match (it averages in a 0); we score the located end and take a fixed discount.
    """
    confidence = float(project["confidence"])
    required = 2 if project.get("endpoint_b") else 1
    located = sum(1 for key in ("lat_a", "lat_b") if project.get(key) not in ("", None))
    if 0 < located < required:
        return min(1.0, confidence * required / located) * PARTIAL_LOCATION_FACTOR
    return confidence


def time_score(overlap):
    """1.0 when the shorter build window sits fully inside the other; 0.7 when they only touch;
    fades to 0 over three years of gap between non-overlapping windows."""
    if overlap.get("window_gap_days") is None:
        return 0.0
    if overlap["windows_overlap"]:
        shorter = overlap["shorter_window_days"]
        share = 1.0 if not shorter else min(1.0, overlap["overlap_days"] / shorter)
        return OVERLAP_BASE + (1 - OVERLAP_BASE) * share
    return OVERLAP_BASE * max(0.0, 1 - overlap["window_gap_days"] / WINDOW_FADE_DAYS)


def score_overlap(overlap, projects_by_id):
    """Apply the team scoring formula to one overlap."""
    gpc = projects_by_id[overlap["project_id_gpc"]]
    desc = projects_by_id[overlap["project_id_desc"]]
    voltage_score = 1.0 if overlap["voltage_match"] else 0.0
    confidence = min(effective_confidence(gpc), effective_confidence(desc))
    return (
        DISTANCE_WEIGHT * distance_score(overlap["distance_mi"])
        + TIME_WEIGHT * time_score(overlap)
        + VOLTAGE_WEIGHT * voltage_score
    ) * (CONFIDENCE_FLOOR + (1 - CONFIDENCE_FLOOR) * confidence)


def rank_overlaps(projects, routes=None):
    projects_by_id = {project["project_id"]: project for project in projects}
    overlaps = find_overlaps(projects, routes=routes)
    for overlap in overlaps:
        overlap["score"] = score_overlap(overlap, projects_by_id)

    overlaps.sort(key=lambda overlap: (-overlap["score"], overlap["project_id_gpc"], overlap["project_id_desc"]))
    for rank, overlap in enumerate(overlaps, start=1):
        overlap["overlap_id"] = f"OVL_{rank}"
        overlap["rank"] = rank
        overlap["score"] = round(overlap["score"], 3)
        overlap.pop("shorter_window_days", None)
    return overlaps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_PROJECTS, help="Geocoded projects CSV")
    parser.add_argument("--output", type=Path, help="Optional destination for ranked overlaps CSV")
    args = parser.parse_args()

    with args.input.open(newline="", encoding="utf-8-sig") as source:
        projects = list(csv.DictReader(source))
    required = {"project_id", "utility", "lat_center", "lon_center", "confidence"}
    if not projects or not required.issubset(projects[0]):
        parser.error("input must contain geocoded projects with a confidence column")

    overlaps = rank_overlaps(projects)
    if args.output:
        columns = ["overlap_id", "project_id_gpc", "project_id_desc", "distance_mi", "band", "time_gap_days",
                   "windows_overlap", "overlap_days", "window_gap_days", "lat_gpc", "lon_gpc", "lat_desc", "lon_desc", "voltage_match", "score", "rank"]
        with args.output.open("w", newline="", encoding="utf-8") as destination:
            writer = csv.DictWriter(destination, fieldnames=columns)
            writer.writeheader()
            writer.writerows(overlaps)

    for overlap in overlaps:
        print(f"#{overlap['rank']} {overlap['project_id_gpc']} + "
              f"{overlap['project_id_desc']}: score {overlap['score']:.3f}, "
              f"{overlap['distance_mi']:.2f} mi")


if __name__ == "__main__":
    main()
