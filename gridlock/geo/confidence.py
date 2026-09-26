"""Confidence scores for OSM endpoint matches."""

from __future__ import annotations

from overlap import haversine_miles
from geocode import border_distance_mi


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
    if matches.get("a") and matches.get("b") and project.get("length_mi"):
        straight = haversine_miles(project["lat_a"], project["lon_a"], project["lat_b"], project["lon_b"])
        stated = float(project["length_mi"])
        if stated > 0 and straight > max(stated * 3, stated + 10):
            score *= 0.25
    score = round(score, 3)
    result["confidence"] = score
    result["confidence_tier"] = (
        "unmatched" if not any(matches.get(s) for s in required) else
        "high" if score >= 0.8 else "medium" if score >= 0.5 else "low"
    )
    result["human_verified"] = "false"
    return result
