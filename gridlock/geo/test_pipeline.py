"""Regression checks for false OSM matches and durable handoff values."""

import csv

from cost import make_brief
from geocode import match_endpoint
from run_all import apply_manual_fixes


def feature(name, state, osm_id, operator=""):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-84.1, 33.5]},
        "properties": {"name": name, "gridlock_state": state, "osm_id": osm_id, "operator": operator},
    }


def test_generic_and_wrong_state_candidates_do_not_win():
    features = [feature("North Substation", "SC", "wrong-state"),
                feature("North Substation", "GA", "generic"),
                feature("North Dublin Substation", "GA", "correct")]
    match = match_endpoint("NORTH DUBLIN", features, "GA", "GPC")
    assert match["feature"]["properties"]["osm_id"] == "correct"
    assert match_endpoint("NORTH DUBLIN", features[:1], "GA", "GPC") is None


def test_manual_fix_survives_pipeline_rebuild(tmp_path):
    fixes = tmp_path / "manual_fixes.csv"
    with fixes.open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=["project_id", "lat_center", "lon_center", "human_verified"])
        writer.writeheader()
        writer.writerow({"project_id": "GPC_1", "lat_center": "32.1", "lon_center": "-81.2", "human_verified": "true"})
    projects = [{"project_id": "GPC_1", "lat_center": "", "lon_center": "", "confidence": 0,
                 "confidence_tier": "unmatched", "human_verified": "false"}]
    apply_manual_fixes(projects, fixes)
    assert (projects[0]["lat_center"], projects[0]["lon_center"]) == (32.1, -81.2)
    assert projects[0]["confidence_tier"] == "high"
    assert projects[0]["human_verified"] == "true"


def test_cost_brief_states_missing_voltage_and_length_assumptions():
    pair = {"overlap_id": "OVL_1", "project_id_gpc": "GPC_1", "project_id_desc": "DESC_1"}
    projects = {"GPC_1": {"length_mi": "", "voltage_kv": ""},
                "DESC_1": {"length_mi": "", "voltage_kv": "", "est_cost_usd": "11700000"}}
    brief = make_brief(pair, projects)
    assert brief["shared_corridor_mi"] == 2
    assert brief["row_width_ft"] == 100
    assert brief["est_land_savings_usd"] == round(2 * 5280 * 100 / 43560 * 10000)
    assert "because at least one project" in brief["assumptions_note"]
    assert "$11,700,000" in brief["assumptions_note"]


def test_cost_brief_accepts_shared_mi_and_cost_overrides():
    pair = {"overlap_id": "OVL_1", "project_id_gpc": "GPC_1", "project_id_desc": "DESC_1"}
    projects = {"GPC_1": {"length_mi": "10", "voltage_kv": "230"}, "DESC_1": {"length_mi": "3", "voltage_kv": "230"}}
    default = make_brief(pair, projects)
    assert default["shared_corridor_mi"] == 3 and default["row_width_ft"] == 150   # shorter length, 230 kV width

    overridden = make_brief(pair, projects, shared_mi=8, land_cost_per_acre_usd=25000)
    assert overridden["shared_corridor_mi"] == 8
    assert overridden["land_cost_per_acre_usd"] == 25000
    assert overridden["row_width_ft"] == 150   # width still comes from voltage, not the override
    expected_acres = 8 * 5280 * 150 / 43560
    assert overridden["shared_acres"] == round(expected_acres, 2)
    assert overridden["est_land_savings_usd"] == round(expected_acres * 25000)
    assert "8 shared corridor miles" in overridden["assumptions_note"]
    assert "were given, not assumed" in overridden["assumptions_note"]
