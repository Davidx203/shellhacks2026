from pathlib import Path

import pytest

from pipeline.common import endpoints, max_kv
from pipeline.parse_gpc import parse_all, parse_text

GPC = Path(__file__).resolve().parents[2] / "data" / "raw" / "gpc_irp_vol3.txt"

SNIPPET = """ 
    Page 44 of 304 
 
THALMANN AND COLERAIN 23O KV LINE RELAY PANEL UPGRADES 
Teams # 21046 
Need Date 06/01/2025 Start Date 12/01/2024 
Description 
 
SAV: GOSHEN (SAV) - MCINTOSH 115KV LINE REBUILD 
Teams # 99999 
Need Date 12/31/2026 Start Date 01/01/2024 
Description 
"""


@pytest.mark.parametrize("name,a,b", [
    ("SAV: GOSHEN (SAV) - MCINTOSH 115KV LINE REBUILD", "GOSHEN", "MCINTOSH"),
    ("SAV: MCINTOSH - PURRYSBURG 230KV REACTORS", "MCINTOSH", "PURRYSBURG"),
    ("SAV: LITTLE OGEECHEE 230-115KV: RELAY MODERNIZATION", "LITTLE OGEECHEE", ""),
    ("SCOTTDALE RELAY MODERNIZATION", "SCOTTDALE", ""),
    ("GTC: EATONTON PRIMARY (035591) - LICK CREEK 115KV REBUILD", "EATONTON PRIMARY", "LICK CREEK"),
    ("FARLEY (APC)-TAZEWELL 500KV", "FARLEY", "TAZEWELL"),
    ("SAV: CC - BIG OGEECHEE 500/230KV (CC NETWORK IMPROVEMENTS)", "BIG OGEECHEE", ""),
    ("GTC: TALBOT #2 - TAZEWELL 500KV LINE", "TALBOT", "TAZEWELL"),
    ("BAINBRIDGE TRANSMISSION: EAST RIVER ROAD, EAST BAINBRIDGE", "BAINBRIDGE", ""),
    ("SWITCH WAY - THORNTON ROAD 230KV", "SWITCH WAY", "THORNTON ROAD"),
    ("NEW CAVENDER DRIVE - TRIBUTARY 230KV LINE", "NEW CAVENDER DRIVE", "TRIBUTARY"),
])
def test_gpc_endpoints(name, a, b):
    assert endpoints(name) == (a, b)


@pytest.mark.parametrize("name,kv", [
    ("THALMANN AND COLERAIN 23O KV LINE", 230),
    ("GTC: HOPEWELL 230/115 KV BANK A", 230),
    ("BOWEN #10 500/230KV AUTOBANK REPLACEMENT", 500),
    ("ATHENA - EAST WATKINSVILLE 115 KV (REBUILD)", 115),
    ("SMART VALVE INSTALLATION", None),
])
def test_gpc_kv(name, kv):
    assert max_kv(name) == kv


def test_parse_text_snippet():
    rows = parse_text(SNIPPET)
    assert len(rows) == 2
    r = rows[0]
    assert r["project_id"] == "GPC_21046"
    assert r["utility"] == "GPC" and r["state"] == "GA"
    assert r["project_name"] == "THALMANN AND COLERAIN 23O KV LINE RELAY PANEL UPGRADES"
    assert (r["endpoint_a"], r["endpoint_b"]) == ("THALMANN", "")
    assert r["voltage_kv"] == 230
    assert r["in_service_date"] == "2025-06-01" and r["start_date"] == "2024-12-01"
    assert r["est_cost_usd"] is None and r["length_mi"] is None
    assert r["source_ref"] == "Teams # 21046"
    assert rows[1]["project_name"] == "SAV: GOSHEN (SAV) - MCINTOSH 115KV LINE REBUILD"
    assert (rows[1]["endpoint_a"], rows[1]["endpoint_b"]) == ("GOSHEN", "MCINTOSH")


needs_raw = pytest.mark.skipif(not GPC.exists(), reason="run extract_pdfs.py first")


@needs_raw
def test_all_208_rows():
    rows = parse_all(GPC)
    assert len(rows) == 208
    assert len({r["project_id"] for r in rows}) == 208
    assert all(r["in_service_date"] and r["start_date"] for r in rows)
    assert all(r["endpoint_a"] for r in rows)
    assert all(len(r["project_name"]) < 100 for r in rows)
    kv = sum(1 for r in rows if r["voltage_kv"])
    assert kv == 165, kv  # the other 43 names carry no kV at all
