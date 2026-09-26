"""Starter-sheet contract checks and independent ranking expectations."""

import csv
from pathlib import Path

import pytest

from overlap import find_overlaps
from rank import rank_overlaps, score_overlap


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
        ("GPC_3", "DESC_5"), ("GPC_1", "DESC_1"), ("GPC_2", "DESC_5"),
    ]
    assert [(p["overlap_id"], p["rank"]) for p in pairs] == [(f"OVL_{i}", i) for i in range(1, 7)]
    lookup = {p["project_id"]: p for p in projects}
    first = pairs[0]
    expected = (0.6 * (1 - 5.65 / 25) + 0.3 * (1 - 152 / 1825) + 0.1) * 1.0
    assert score_overlap(first, lookup) == pytest.approx(expected)
