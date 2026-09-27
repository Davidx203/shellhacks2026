"""Starter-sheet contract checks and independent ranking expectations."""

import csv
from pathlib import Path

import pytest

from overlap import band_for, find_overlaps
from rank import distance_score, effective_confidence, rank_overlaps, score_overlap, time_score
from timeline import window_relation


FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "projects.csv"
EXPECTED = {
    ("GPC_1", "DESC_2"): (4.09, 3074),
    ("GPC_2", "DESC_3"): (5.65, 152),
    ("GPC_3", "DESC_3"): (7.55, 517),
    ("GPC_1", "DESC_1"): (8.01, 3074),
    ("GPC_2", "DESC_5"): (14.34, 365),
    ("GPC_3", "DESC_5"): (14.81, 730),
}


@pytest.fixture
def projects():
    with FIXTURE.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def test_all_six_fixture_pairs(projects):
    actual = {(p["project_id_gpc"], p["project_id_desc"]): (p["distance_mi"], p["time_gap_days"])
              for p in find_overlaps(projects)}
    assert actual == EXPECTED


def test_scoring_formula_and_rank_order(projects):
    pairs = rank_overlaps(projects)
    assert [(p["project_id_gpc"], p["project_id_desc"]) for p in pairs] == [
        ("GPC_2", "DESC_3"), ("GPC_3", "DESC_3"), ("GPC_1", "DESC_2"),
        ("GPC_1", "DESC_1"), ("GPC_2", "DESC_5"), ("GPC_3", "DESC_5"),
    ]
    assert [(p["overlap_id"], p["rank"]) for p in pairs] == [(f"OVL_{i}", i) for i in range(1, 7)]
    lookup = {p["project_id"]: p for p in projects}
    first = pairs[0]
    confidence = min(effective_confidence(lookup[first["project_id_gpc"]]), effective_confidence(lookup[first["project_id_desc"]]))
    expected = (0.60 * (1 - 5.65 / 25) ** 0.7 + 0.35 * time_score(first) + 0.05) * (0.75 + 0.25 * confidence)
    assert score_overlap(first, lookup) == pytest.approx(expected)


def project(pid, utility, lat_a=None, lon_a=None, lat_b=None, lon_b=None, start="", end="2026-06-01", **extra):
    def num(v):
        return "" if v is None else str(v)
    center = ((lat_a + (lat_b if lat_b is not None else lat_a)) / 2, (lon_a + (lon_b if lon_b is not None else lon_a)) / 2)
    return {"project_id": pid, "utility": utility, "lat_a": num(lat_a), "lon_a": num(lon_a), "lat_b": num(lat_b),
            "lon_b": num(lon_b), "lat_center": str(center[0]), "lon_center": str(center[1]),
            "in_service_date": end, "build_start": start, "build_end": end, "voltage_kv": "115",
            "human_verified": "false", "confidence": "1.0", **extra}


def test_crossing_lines_overlap_even_when_centers_are_far_apart():
    long_ns = project("G", "GPC", 32.0, -81.0, 32.6, -81.0)      # ~41 mi north-south line
    long_ew = project("D", "DESC", 32.3, -81.35, 32.3, -80.65)   # ~41 mi east-west line crossing it
    pair = find_overlaps([long_ns, long_ew])[0]
    assert pair["distance_mi"] == 0.0 and pair["band"] == "crossing"


def test_line_passing_near_a_substation_counts_by_closest_point():
    line = project("G", "GPC", 32.0, -81.0, 32.6, -81.0)
    substation = project("D", "DESC", 32.3, -80.96)               # ~2.3 mi east of the line
    pair = find_overlaps([line, substation])[0]
    assert 2.0 < pair["distance_mi"] < 2.7 and pair["band"] == "share_logistics"


def test_route_geometry_replaces_the_straight_segment():
    a = project("G", "GPC", 32.0, -81.0, 32.0, -80.8)
    d = project("D", "DESC", 32.2, -80.9)
    straight = find_overlaps([a, d])[0]["distance_mi"]
    routes = {"G": [(32.0, -81.0), (32.19, -80.9), (32.0, -80.8)]}   # route bows up toward D
    routed = find_overlaps([a, d], routes=routes)[0]["distance_mi"]
    assert routed < straight


def test_bands():
    assert [band_for(x) for x in (0.0, 0.05, 0.9, 4.9, 24.0)] == [
        "crossing", "crossing", "share_land", "share_logistics", "share_crews"]


def test_window_relation_and_time_score():
    a = project("G", "GPC", 32.0, -81.0, start="2025-01-01", end="2026-12-31")
    b = project("D", "DESC", 32.0, -81.0, start="2026-01-01", end="2027-06-30")
    rel = window_relation(a, b)
    assert rel["windows_overlap"] and rel["overlap_days"] == 364
    far = project("D2", "DESC", 32.0, -81.0, start="2030-01-01", end="2030-12-31")
    gap = window_relation(a, far)
    assert not gap["windows_overlap"] and gap["window_gap_days"] > 1000
    overlap_pair = find_overlaps([a, b])[0]
    gap_pair = find_overlaps([a, far])[0]
    assert time_score(overlap_pair) > 0.7 > time_score(gap_pair) >= 0.0


def test_distance_is_the_primary_signal_in_the_ranking():
    near_bad_timing = ("G1", project("G1", "GPC", 32.0, -81.0, start="2025-01-01", end="2025-06-01"))
    far_perfect_timing = ("G2", project("G2", "GPC", 32.0, -80.70, start="2026-01-01", end="2026-12-31"))
    desc = project("D", "DESC", 32.0, -81.01, start="2026-01-01", end="2026-12-31")
    pairs = rank_overlaps([near_bad_timing[1], far_perfect_timing[1], desc])
    assert len(pairs) == 2
    assert pairs[0]["project_id_gpc"] == "G1"
    assert pairs[1]["windows_overlap"] and not pairs[0]["windows_overlap"]


def test_distance_score_is_concave_and_bounded():
    assert distance_score(0) == 1.0 and distance_score(25) == 0.0 and distance_score(30) == 0.0
    assert distance_score(3) > 1 - 3 / 25 and distance_score(12.5) > 0.5
    assert distance_score(1) > distance_score(5) > distance_score(20)


def test_partial_location_is_not_treated_as_a_failed_match():
    both = {"confidence": "0.9", "endpoint_b": "B", "lat_a": "1", "lat_b": "2"}
    one_of_two = {"confidence": "0.425", "endpoint_b": "B", "lat_a": "1", "lat_b": ""}   # (0.85 + 0) / 2
    single_site = {"confidence": "0.85", "endpoint_b": "", "lat_a": "1", "lat_b": ""}
    assert effective_confidence(both) == pytest.approx(0.9)
    assert effective_confidence(one_of_two) == pytest.approx(0.85 * 0.85)
    assert effective_confidence(single_site) == pytest.approx(0.85)


def test_implausible_endpoint_pair_is_left_out_of_overlaps():
    wrong_match = project("G", "GPC", 33.8, -80.6, 32.4, -81.1)     # ~100 mi "115 kV line": a bad endpoint match
    near = project("D", "DESC", 33.1, -80.85)                        # sits right under that bogus segment
    assert find_overlaps([wrong_match, near]) == []
    routed = find_overlaps([wrong_match, near], routes={"G": [(33.1, -80.86), (33.1, -80.84)]})
    assert routed and routed[0]["distance_mi"] < 1
