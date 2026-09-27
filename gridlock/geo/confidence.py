"""Confidence scores for OSM endpoint matches."""

from __future__ import annotations

from overlap import haversine_miles
from geocode import border_distance_mi, max_plausible_miles


INFERRED_CEILING = 0.79   # an inferred endpoint can never make a project "high"

OPERATORS = {
    "GPC": ("GEORGIA POWER", "SOUTHERN"),
    "DESC": ("DOMINION", "SCE&G", "SOUTH CAROLINA ELECTRIC"),
}


def state_score(feature: dict, expected: str) -> float:
    props = feature["properties"]
    if props.get("gridlock_state"):
        if props["gridlock_state"] == expected:
            return 1.0
        lon, lat = feature["geometry"]["coordinates"]
        return 0.5 if border_distance_mi(lat, lon) <= 15 else 0.0
    state = (props.get("addr:state") or props.get("is_in:state_code") or props.get("is_in:state") or "").upper()
    if state:
        valid = {"GA", "GEORGIA"} if expected == "GA" else {"SC", "SOUTH CAROLINA"}
        return 1.0 if state in valid else 0.0

    lon, lat = feature["geometry"]["coordinates"]
    # Approximate Savannah River border: coast to Augusta to Lake Hartwell.
    if lat < 32.0 or lat > 35.0 or lon < -83.4 or lon > -80.7:
        return 1.0 if (expected == "GA" and lon < -82.0) or (expected == "SC" and lon > -82.0) else 0.0
    border_lon = -80.85 - (lat - 32.0) * 0.72
    delta = lon - border_lon
    if abs(delta) < 0.2:
        return 0.5
    return 1.0 if (delta < 0) == (expected == "GA") else 0.0


def endpoint_confidence(match: dict | None, utility: str, state: str) -> float:
    if match is None:
        return 0.0
    feature = match["feature"]
    operator = (feature["properties"].get("operator") or "").upper()
    operator_score = 0.5 if not operator else float(any(token in operator for token in OPERATORS[utility]))
    return 0.5 * match["name_score"] / 100 + 0.3 * operator_score + 0.2 * state_score(feature, state)


def score_project(project: dict, matches: dict) -> dict:
    result = dict(project)
    required = ["a"] + (["b"] if project.get("endpoint_b") else [])
    score = sum(endpoint_confidence(matches.get(s), project["utility"], project["state"]) for s in required) / len(required)
    if matches.get("a") and matches.get("b"):
        straight = haversine_miles(project["lat_a"], project["lon_a"], project["lat_b"], project["lon_b"])
        if straight > max_plausible_miles(project):
            score *= 0.25
    if any(m and m.get("inferred") for m in matches.values()):
        score = min(score, INFERRED_CEILING)
    score = round(score, 3)
    result["confidence"] = score
    result["confidence_tier"] = tier_for(score, any(matches.get(s) for s in required))
    result["human_verified"] = "false"
    return result


def tier_for(score: float, any_match: bool) -> str:
    return "unmatched" if not any_match else "high" if score >= 0.8 else "medium" if score >= 0.5 else "low"


def apply_route_evidence(project: dict) -> None:
    """A route along same-voltage lines matching any stated length is evidence the pair is right."""
    if project.get("route_mi") in ("", None) or project["confidence_tier"] == "unmatched":
        return
    route = float(project["route_mi"])
    stated = float(project["length_mi"]) if project.get("length_mi") else None
    if stated and not (0.5 * stated <= route <= 2 * stated):
        return
    ceiling = INFERRED_CEILING if "inferred" in str(project.get("geocode_method", "")) else 1.0
    project["confidence"] = round(min(ceiling, float(project["confidence"]) + 0.1), 3)
    project["confidence_tier"] = tier_for(project["confidence"], True)
