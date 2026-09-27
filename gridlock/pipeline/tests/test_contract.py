import csv
from pathlib import Path

import pytest

from pipeline.common import COLUMNS
from pipeline.validate import validate

CSV = Path(__file__).resolve().parents[2] / "data" / "interim" / "projects_raw.csv"


def good():
    return {
        "project_id": "GPC_1", "utility": "GPC", "state": "GA", "project_name": "X",
        "endpoint_a": "X", "endpoint_b": "", "voltage_kv": "230", "project_type": "relay",
        "length_mi": "", "est_cost_usd": "", "start_date": "2024-01-01",
        "in_service_date": "2026-06-01", "build_start": "2024-01-01", "build_end": "2026-06-01", "source_file": "f", "source_ref": "r",
    }


def test_good_row_passes():
    assert validate([good()]) == []


@pytest.mark.parametrize("field,value", [
    ("in_service_date", "06/01/2026"), ("voltage_kv", "230.0"), ("utility", "XYZ"),
    ("project_type", ""), ("state", "SC"), ("est_cost_usd", "$3,000"), ("in_service_date", ""),
])
def test_validator_catches_bad_rows(field, value):
    r = good()
    r[field] = value
    assert validate([r])


def test_validator_catches_inverted_build_window():
    r = good()
    r["build_start"], r["build_end"] = "2027-01-01", "2026-06-01"
    assert validate([r])


def test_validator_catches_duplicates():
    assert validate([good(), good()])


@pytest.mark.skipif(not CSV.exists(), reason="run pipeline/build_raw.py first")
def test_real_csv_meets_contract():
    with CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert reader.fieldnames == COLUMNS
    assert validate(rows) == []
    assert {r["utility"] for r in rows} <= {"GPC", "DESC"}
