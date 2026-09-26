import csv
import re
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[2] / "data"
FIXTURES = DATA / "fixtures" / "projects.csv"
RAW = DATA / "interim" / "projects_raw.csv"


def norm(name):
    return re.sub(r"[\s/–—-]+", "", name).lower()


@pytest.mark.skipif(not (FIXTURES.exists() and RAW.exists()), reason="fixtures or raw csv missing")
def test_starter_projects_match_parsed_data():
    parsed = {}
    for r in csv.DictReader(RAW.open(encoding="utf-8")):
        parsed.setdefault(norm(r["project_name"]), r)
    starters = list(csv.DictReader(FIXTURES.open(encoding="utf-8")))
    assert len(starters) == 10
    for s in starters:
        p = parsed.get(norm(s["project_name"]))
        assert p, f"no parsed row for {s['project_name']}"
        assert p["voltage_kv"] == s["voltage_kv"], s["project_name"]
        assert p["in_service_date"] == s["in_service_date"], s["project_name"]
