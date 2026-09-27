"""Endpoint pairing must produce plausible lines, not just the best name per endpoint."""

from confidence import score_project
from geocode import geocode_project, max_plausible_miles


def sub(name, lat, lon, osm_id, state="GA", operator="Georgia Power"):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": name, "gridlock_state": state, "osm_id": osm_id, "operator": operator},
    }


def project(name, a, b, kv="115", **extra):
    return {"project_id": "GPC_T", "utility": "GPC", "state": "GA", "project_name": name,
            "endpoint_a": a, "endpoint_b": b, "voltage_kv": kv, "length_mi": "", **extra}


FEATURES = [
    sub("Goshen", 33.60, -82.90, "goshen-far"),
    sub("Goshen", 32.20, -81.15, "goshen-near"),
    sub("McIntosh", 32.30, -81.20, "mcintosh"),
]


def test_pair_choice_picks_the_goshen_that_forms_a_plausible_line():
    located, matches = geocode_project(project("GOSHEN - MCINTOSH 115KV LINE REBUILD", "GOSHEN", "MCINTOSH"), FEATURES)
    assert located["osm_id_a"] == "goshen-near"
    assert located["osm_id_b"] == "mcintosh"


def test_implausible_only_pair_is_demoted():
    far = [sub("Goshen", 33.60, -82.90, "goshen-far"), sub("McIntosh", 32.30, -81.20, "mcintosh")]
    p = project("GOSHEN - MCINTOSH 115KV LINE REBUILD", "GOSHEN", "MCINTOSH")
    located, matches = geocode_project(p, far)
    scored = score_project(located, matches)
    assert scored["confidence"] < 0.5
    assert scored["confidence_tier"] == "low"


def test_sav_prefix_prefers_savannah_area_candidates():
    features = [sub("Goshen", 33.60, -82.90, "goshen-far"), sub("Goshen", 32.20, -81.15, "goshen-near")]
    located, _ = geocode_project(project("SAV: GOSHEN 115KV BANK", "GOSHEN", ""), features)
    assert located["osm_id_a"] == "goshen-near"


def test_plausible_length_uses_stated_length_then_voltage():
    assert max_plausible_miles({"length_mi": "10", "voltage_kv": "115"}) == 30
    assert max_plausible_miles({"length_mi": "", "voltage_kv": "115"}) == 60
    assert max_plausible_miles({"length_mi": "", "voltage_kv": ""}) == 100


def test_abbreviations_match_spelled_out_names():
    features = [sub("Saint George", 33.19, -80.58, "stg", state="SC", operator="Dominion Energy")]
    p = {**project("St George - Sumter 230kV: Rebuild", "St George", ""), "utility": "DESC", "state": "SC"}
    located, _ = geocode_project(p, features)
    assert located["osm_id_a"] == "stg"


def test_relaxed_match_needs_a_distinctive_word():
    features = [sub("Saluda", 34.0, -81.7, "saluda", state="SC", operator="Dominion Energy"),
                sub("North Dublin", 32.5, -82.9, "nd", state="GA")]
    p = {**project("SALUDA COUNTY - X 115KV", "Saluda County", ""), "utility": "DESC", "state": "SC"}
    located, _ = geocode_project(p, features)
    assert located["osm_id_a"] == "saluda"
    generic = {**project("NORTH 115KV", "North", "")}
    assert geocode_project(generic, features)[0]["osm_id_a"] == ""


def test_ambiguous_relaxed_single_endpoint_is_dropped():
    features = [sub("Dawson Crossing", 34.4, -83.9, "d1"), sub("Dawson Junction", 31.7, -84.4, "d2")]
    located, _ = geocode_project(project("DAWSON 230KV BANK", "DAWSON", ""), features)
    assert located["osm_id_a"] == ""
