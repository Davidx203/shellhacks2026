"""Score and rank cross-utility project overlaps."""

import argparse
import csv
from pathlib import Path

from overlap import find_overlaps


DEFAULT_PROJECTS = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "projects.csv"
DISTANCE_WEIGHT = 0.6
TIME_WEIGHT = 0.3
VOLTAGE_WEIGHT = 0.1
MAX_DISTANCE_MI = 25.0
TIME_WINDOW_DAYS = 1825


def score_overlap(overlap, projects_by_id):
    """Apply the team scoring formula to one overlap."""
    gpc = projects_by_id[overlap["project_id_gpc"]]
    desc = projects_by_id[overlap["project_id_desc"]]
    distance_score = max(0.0, 1 - overlap["distance_mi"] / MAX_DISTANCE_MI)
    time_gap = overlap["time_gap_days"]
    time_score = max(0.0, 1 - time_gap / TIME_WINDOW_DAYS) if time_gap is not None else 0.0
    voltage_score = 1.0 if overlap["voltage_match"] else 0.0
    confidence = min(float(gpc["confidence"]), float(desc["confidence"]))
    return (
        DISTANCE_WEIGHT * distance_score
        + TIME_WEIGHT * time_score
        + VOLTAGE_WEIGHT * voltage_score
    ) * (0.5 + 0.5 * confidence)


def rank_overlaps(projects):
    projects_by_id = {project["project_id"]: project for project in projects}
    overlaps = find_overlaps(projects)
    for overlap in overlaps:
        overlap["score"] = score_overlap(overlap, projects_by_id)

    overlaps.sort(key=lambda overlap: (-overlap["score"], overlap["project_id_gpc"], overlap["project_id_desc"]))
    for rank, overlap in enumerate(overlaps, start=1):
        overlap["overlap_id"] = f"OVL_{rank}"
        overlap["rank"] = rank
        overlap["score"] = round(overlap["score"], 3)
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
        columns = ["overlap_id", "project_id_gpc", "project_id_desc", "distance_mi",
                   "time_gap_days", "voltage_match", "score", "rank"]
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
