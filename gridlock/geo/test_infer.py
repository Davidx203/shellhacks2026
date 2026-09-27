from confidence import score_project
from geocode import geocode_project
from infer import Inferrer
from routes import PowerGrid


def way(points, voltage="115000"):
    return {"tags": {"voltage": voltage}, "geometry": [{"lat": la, "lon": lo} for la, lo in points]}


def sub(osm_id, lat, lon, voltage="115000", operator="", state="SC", name=""):
    props = {"osm_id": osm_id, "voltage": voltage, "operator": operator, "gridlock_state": state}
    if name:
        props["name"] = name
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


LINE = way([(32.0, -81.0 + i * 0.01) for i in range(7)])                # about 3.5 mi east of the anchor
ANCHOR = sub("anchor", 32.0, -81.0, name="Hooks", operator="Dominion Energy")
FEATURES = [ANCHOR]


def project(name_a, name_b, length="3.5", **extra):
    return {"project_id": "DESC_T", "utility": "DESC", "state": "SC", "project_name": f"{name_a} - {name_b} 115kV: Rebuild",
            "endpoint_a": name_a, "endpoint_b": name_b, "voltage_kv": "115", "length_mi": length, **extra}


def inferrer(subs, place=None):
    return Inferrer(subs, PowerGrid([LINE]), lambda name, state: place)


def test_missing_end_is_found_at_the_stated_length_along_the_line():
    subs = [sub("end", 32.0, -80.94), sub("decoy-near", 32.0, -80.985), sub("decoy-far", 32.0, -80.90)]
    located, matches = geocode_project(project("Hooks", "Thurmond"), FEATURES, inferrer(subs))
    assert located["osm_id_a"] == "anchor" and located["osm_id_b"] == "end"
    assert located["geocode_method"] == "a:name;b:inferred_route"


def test_inferred_endpoints_never_reach_high_confidence():
    subs = [sub("end", 32.0, -80.94, operator="Dominion Energy")]
    located, matches = geocode_project(project("Hooks", "Thurmond"), FEATURES, inferrer(subs))
    assert score_project(located, matches)["confidence_tier"] in {"low", "medium"}


def test_ambiguous_candidates_are_not_guessed():
    subs = [sub("east", 32.0, -80.94), sub("mid", 32.0, -80.95)]         # both on the line, no length to decide
    located, _ = geocode_project(project("Hooks", "Thurmond", length=""), FEATURES, inferrer(subs))
    assert located["osm_id_b"] == ""


def test_other_operators_and_off_line_substations_are_excluded():
    subs = [sub("coop", 32.0, -80.94, operator="Blue Ridge EMC"), sub("off-line", 32.05, -80.94)]
    located, _ = geocode_project(project("Hooks", "Thurmond"), FEATURES, inferrer(subs))
    assert located["osm_id_b"] == ""


def test_place_only_inference_still_requires_the_voltage_tag():
    subs = [sub("wrong-kv", 32.30, -80.95, voltage="230000")]
    p = {**project("Okatie", ""), "endpoint_b": "", "length_mi": ""}
    located, _ = geocode_project(p, [], inferrer(subs, place=(32.295, -80.945)))
    assert located["osm_id_a"] == ""


def test_place_hint_alone_locates_a_single_site_project_on_the_nearest_substation():
    subs = [sub("town-sub", 32.30, -80.95), sub("other", 32.50, -80.60)]
    p = {**project("Okatie", ""), "endpoint_b": "", "length_mi": ""}
    located, _ = geocode_project(p, [], inferrer(subs, place=(32.295, -80.945)))
    assert located["osm_id_a"] == "town-sub" and located["geocode_method"] == "a:inferred_place"


def test_no_place_and_no_anchor_means_no_guess():
    subs = [sub("s", 32.0, -80.94)]
    p = {**project("Okatie", ""), "endpoint_b": "", "length_mi": ""}
    located, _ = geocode_project(p, [], inferrer(subs, place=None))
    assert located["osm_id_a"] == ""


def test_route_and_place_agree_beats_either_alone():
    subs = [sub("right", 32.0, -80.94), sub("near-place-only", 32.2, -80.90)]
    located, _ = geocode_project(project("Hooks", "Thurmond"), FEATURES, inferrer(subs, place=(32.0, -80.94)))
    assert located["osm_id_b"] == "right" and located["geocode_method"].endswith("inferred_route+place")


def test_a_same_named_town_far_from_the_located_end_is_ignored():
    subs = [sub("end", 32.0, -80.94)]
    far_town = (34.17, -79.09)
    located, _ = geocode_project(project("Hooks", "Thurmond"), FEATURES, inferrer(subs, place=far_town))
    assert located["osm_id_b"] == "end" and located["geocode_method"] == "a:name;b:inferred_route"


def test_route_fit_does_not_require_the_substation_to_carry_the_voltage_tag():
    subs = [sub("end", 32.0, -80.94, voltage="69000")]                    # incomplete OSM tagging
    located, _ = geocode_project(project("Hooks", "Thurmond"), FEATURES, inferrer(subs))
    assert located["osm_id_b"] == "end"


def test_explicit_operator_match_breaks_a_tie_between_nearby_substations():
    subs = [sub("plain", 32.30, -80.95), sub("utility", 32.30, -80.97, operator="South Carolina Electric & Gas")]
    p = {**project("Okatie", ""), "endpoint_b": "", "length_mi": ""}
    located, _ = geocode_project(p, [], inferrer(subs, place=(32.30, -80.96)))
    assert located["osm_id_a"] == "utility"


def test_town_hint_still_locates_the_end_when_the_line_network_has_a_gap():
    subs = [sub("gap-sub", 32.05, -80.96)]                              # about 4.5 mi from the anchor but off LINE
    located, _ = geocode_project(project("Hooks", "Okatie"), FEATURES, inferrer(subs, place=(32.05, -80.96)))
    assert located["osm_id_b"] == "gap-sub"
