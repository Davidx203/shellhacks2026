from pathlib import Path

import pytest

from pipeline.common import endpoints, iso_date, max_kv
from pipeline.parse_desc import parse_page, parse_all

PAGES = Path(__file__).resolve().parents[2] / "data" / "raw" / "desc_pages"

PAGE_43 = """Project 43 of 44 
 
Dominion Energy South Carolina 
Planned Transmission Projects $2M and above Total 
5 Year Budget 
 
Urquhart – Aiken PSA 46 kV: Rebuild 
 
Project ID 
6810 O 
 
Project Description 
Rebuilding the section of 46 kV line from Urquhart to the Aiken PSA tap point. TBD if the scope of this 
project includes rebuilding the actual tap Aiken PSA.  4.5 miles. 
 
Project Need 
System hardening 
 
Project Status 
Planned 
 
Planned In-Service Date 
12/31/2027 
 
Estimated Project Cost 
Previous 
2024 
2025 
2026 
2027 
2028 
Total* 
$0 
$0 
 
$0 
 
$0 
 
$3,000,000 
$0 
$3,000,000 
 
 
*Total Estimated Amount applied to 2027 Rate Base Calculation 
"""


def test_iso_dates():
    assert iso_date("12/31/2027") == "2027-12-31"
    assert iso_date("06/01/24") == "2024-06-01"
    assert iso_date("9/30/2024") == "2024-09-30"
    assert iso_date("10/1/2025 (phase 1) and 10/1/2026 (phase 2)") == "2025-10-01"
    assert iso_date("") == ""


@pytest.mark.parametrize("name,a,b", [
    ("Urquhart – Aiken PSA 46 kV: Rebuild", "Urquhart", "Aiken PSA"),
    ("Okatie-Bluffton 115kV: Rebuild", "Okatie", "Bluffton"),
    ("Hooks - Thurmond 115kV Tie: Rebuild", "Hooks", "Thurmond"),
    ("Stevens Creek - Hooks 115kV/LR Plumb Branch 46kV Rebuilds", "Stevens Creek", "Hooks"),
    ("Goose Creek Reservoir: Rebuild Transmission Line Crossings", "Goose Creek Reservoir", ""),
])
def test_endpoints(name, a, b):
    assert endpoints(name) == (a, b)


def test_kv():
    assert max_kv("Stevens Creek - Hooks 115kV/LR Plumb Branch 46kV Rebuilds") == 115
    assert max_kv("Union Pier 115-13.8 kV Sub: Tap") == 115
    assert max_kv("THALMANN AND COLERAIN 23O KV LINE") == 230
    assert max_kv("LITTLE OGEECHEE 230-115KV: RELAY") == 230
    assert max_kv("SCOTTDALE RELAY MODERNIZATION") is None


def test_parse_page_43():
    r = parse_page(PAGE_43, "desc_pages/43.txt")
    assert r["project_id"] == "DESC_6810O"
    assert r["utility"] == "DESC" and r["state"] == "SC"
    assert r["project_name"] == "Urquhart – Aiken PSA 46 kV: Rebuild"
    assert (r["endpoint_a"], r["endpoint_b"]) == ("Urquhart", "Aiken PSA")
    assert r["voltage_kv"] == 46
    assert r["length_mi"] == 4.5
    assert r["est_cost_usd"] == 3000000
    assert r["in_service_date"] == "2027-12-31"
    assert r["start_date"] == ""
    assert r["source_ref"] == "Project 43 of 44"


needs_raw = pytest.mark.skipif(not PAGES.exists(), reason="run extract_pdfs.py first")


@needs_raw
def test_all_44_rows():
    rows = parse_all(PAGES)
    assert len(rows) == 44
    assert len({r["project_id"] for r in rows}) == 44
    assert all(r["in_service_date"] for r in rows)
    assert all(isinstance(r["est_cost_usd"], int) and r["est_cost_usd"] > 0 for r in rows)
    assert all(r["endpoint_a"] for r in rows)


@needs_raw
def test_multiline_name_and_two_dates():
    by_id = {r["project_id"]: r for r in parse_all(PAGES)}
    assert by_id["DESC_6341A-F"]["project_name"].endswith("#2:") or "Hamlin" in by_id["DESC_6341A-F"]["project_name"]
    assert by_id["DESC_6859"]["in_service_date"] == "2025-10-01"
