from confidence import SUBMISSION_CEILING, apply_submission_ceiling, score_project
from geocode import geocode_project


def sub(osm_id, lat, lon, name, state="SC", operator="Dominion Energy"):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"osm_id": osm_id, "name": name, "gridlock_state": state, "operator": operator}}


def project(**over):
    row = {"project_id": "DESC_SUB1", "utility": "DESC", "state": "SC", "project_name": "Okatie - Bluffton 115kV: Rebuild",
           "endpoint_a": "Okatie", "endpoint_b": "Bluffton", "voltage_kv": "115", "length_mi": "",
           "given_lat_a": "", "given_lon_a": "", "given_lat_b": "", "given_lon_b": "", "origin": "form"}
    row.update(over)
    return row


FEATURES = [sub("bluffton", 32.235, -80.853, "Bluffton Substation"), sub("okatie-wrong", 34.0, -81.0, "Okatie Substation")]


def test_given_coordinates_locate_the_endpoint_and_skip_name_matching():
    located, matches = geocode_project(project(given_lat_a="32.2776", given_lon_a="-80.9686"), FEATURES)
    assert (located["lat_a"], located["lon_a"]) == (32.2776, -80.9686)
    assert located["osm_id_a"] == "submitted"
    assert located["geocode_method"] == "a:submitted_coordinates;b:name"
    assert located["osm_id_b"] == "bluffton"


def test_without_given_coordinates_behaviour_is_unchanged():
    located, _ = geocode_project(project(), FEATURES)
    assert located["geocode_method"].startswith("a:name")


def test_given_coordinates_score_as_a_confident_endpoint():
    located, matches = geocode_project(project(endpoint_b="", given_lat_a="32.2776", given_lon_a="-80.9686"), FEATURES)
    scored = score_project(located, matches)
    assert scored["confidence"] >= 0.8


def test_unverified_submissions_are_capped_and_reports_are_not():
    submitted = {"origin": "form", "confidence": 0.95, "confidence_tier": "high", "human_verified": "false"}
    apply_submission_ceiling(submitted)
    assert submitted["confidence"] == SUBMISSION_CEILING == 0.6 and submitted["confidence_tier"] == "medium"
    report = {"origin": "report", "confidence": 0.95, "confidence_tier": "high", "human_verified": "false"}
    apply_submission_ceiling(report)
    assert report["confidence"] == 0.95 and report["confidence_tier"] == "high"
    legacy = {"confidence": 0.95, "confidence_tier": "high", "human_verified": "false"}
    apply_submission_ceiling(legacy)
    assert legacy["confidence"] == 0.95


def test_the_ceiling_keeps_low_scores_and_unmatched_tier():
    low = {"origin": "pdf", "confidence": 0.3, "confidence_tier": "low", "human_verified": "false"}
    apply_submission_ceiling(low)
    assert low["confidence"] == 0.3 and low["confidence_tier"] == "low"
    unmatched = {"origin": "pdf", "confidence": 0.0, "confidence_tier": "unmatched", "human_verified": "false"}
    apply_submission_ceiling(unmatched)
    assert unmatched["confidence_tier"] == "unmatched"


def test_verified_submissions_are_left_alone():
    verified = {"origin": "form", "confidence": 1.0, "confidence_tier": "high", "human_verified": "true"}
    apply_submission_ceiling(verified)
    assert verified["confidence"] == 1.0
