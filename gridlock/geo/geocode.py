"""Cache OSM substations and match project endpoint names to them."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import requests
from rapidfuzz import fuzz

from overlap import haversine_miles


DATA = Path(__file__).resolve().parents[1] / "data"
CACHE = DATA / "cache" / "substations_ga_sc.geojson"
STATE_CACHE = DATA / "cache" / "ga_sc_states.geojson"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
FALLBACK_URL = "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
OVERPASS_QUERY = '[out:json][timeout:120];nwr["power"="substation"](30.3,-85.7,35.3,-78.5);out center tags;'
MIN_NAME_SCORE = 70
STATE_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/0/query"
BORDER = [(32.03, -80.85), (32.35, -81.15), (33.47, -81.95), (34.48, -82.85), (34.99, -83.10)]
OPERATORS = {"GPC": ("GEORGIA POWER", "SOUTHERN"), "DESC": ("DOMINION", "SCE&G", "SOUTH CAROLINA ELECTRIC")}


def border_distance_mi(lat: float, lon: float) -> float:
    best = math.inf
    for (lat1, lon1), (lat2, lon2) in zip(BORDER, BORDER[1:]):
        scale = math.cos(math.radians(lat))
        dx, dy = (lon2 - lon1) * scale, lat2 - lat1
        t = max(0, min(1, (((lon - lon1) * scale) * dx + (lat - lat1) * dy) / (dx * dx + dy * dy)))
        best = min(best, haversine_miles(lat, lon, lat1 + t * dy, lon1 + t * (lon2 - lon1)))
    return best


def normalize_name(value: str) -> str:
    value = re.sub(r"\([^)]*\)|#\s*\d+", " ", value.upper())
    value = re.sub(r"\b(?:SUBSTATION|SUB|PRIMARY|SAV)\b", " ", value)
    return " ".join(re.findall(r"[A-Z0-9]+", value))


def _inside_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _state_for_point(lon: float, lat: float, states: list[dict]) -> str:
    for state in states:
        geometry = state["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for rings in polygons:
            if _inside_ring(lon, lat, rings[0]) and not any(_inside_ring(lon, lat, hole) for hole in rings[1:]):
                return state["properties"]["STUSAB"]
    return ""


def _load_states(cache: Path = STATE_CACHE) -> list[dict]:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["features"]
    response = requests.get(STATE_URL, params={
        "where": "STUSAB IN ('GA','SC')", "outFields": "STUSAB,NAME",
        "returnGeometry": "true", "outSR": "4326", "f": "geojson",
    }, timeout=90)
    response.raise_for_status()
    payload = response.json()
    if len(payload.get("features", [])) != 2:
        raise ValueError("Census state boundary query did not return GA and SC")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload), encoding="utf-8")
    return payload["features"]


def _annotate_states(features: list[dict], cache: Path) -> list[dict]:
    if all("gridlock_state" in item["properties"] for item in features):
        return features
    states = _load_states(cache.parent / STATE_CACHE.name)
    for item in features:
        lon, lat = item["geometry"]["coordinates"]
        item["properties"]["gridlock_state"] = _state_for_point(lon, lat, states)
    cache.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    return features


def fetch_substations(cache: Path = CACHE) -> list[dict]:
    """Use the local snapshot after the first successful Overpass request."""
    if cache.exists():
        return _annotate_states(json.loads(cache.read_text(encoding="utf-8"))["features"], cache)

    last_error = None
    for url in (OVERPASS_URL, FALLBACK_URL):
        try:
            response = requests.post(url, data={"data": OVERPASS_QUERY},
                                     headers={"User-Agent": "GridlockRadar/1.0 (single cached research query)"},
                                     timeout=150)
            response.raise_for_status()
            break
        except requests.RequestException as error:
            last_error = error
    else:
        raise RuntimeError("Both Overpass instances failed; no cache was written") from last_error
    features = []
    for item in response.json()["elements"]:
        tags = item.get("tags", {})
        point = item.get("center", item)
        if not tags.get("name") or "lat" not in point or "lon" not in point:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [point["lon"], point["lat"]]},
            "properties": {**tags, "osm_id": f'{item["type"]}/{item["id"]}'},
        })
    if not features:
        raise ValueError("Overpass returned no named substations; cache was not written")
    cache.parent.mkdir(parents=True, exist_ok=True)
    return _annotate_states(features, cache)


def match_endpoint(name: str, features: list[dict], expected_state: str, utility: str) -> dict | None:
    normalized = normalize_name(name)
    if not normalized:
        return None
    best = None
    best_score = -1
    for feature in features:
        props = feature["properties"]
        if props.get("gridlock_state") != expected_state:
            lon, lat = feature["geometry"]["coordinates"]
            operator = (props.get("operator") or "").upper()
            if border_distance_mi(lat, lon) > 15 or not any(token in operator for token in OPERATORS[utility]):
                continue
        candidate = normalize_name(feature["properties"].get("name", ""))
        if not candidate:
            continue
        score = fuzz.token_set_ratio(normalized, candidate)
        # token_set_ratio alone gives a perfect score to generic subsets such as
        # NORTH versus NORTH DUBLIN. Require the whole names to resemble each other.
        if fuzz.ratio(normalized, candidate) < 65:
            continue
        if score > best_score:
            best, best_score = feature, score
    if best_score < MIN_NAME_SCORE:
        return None
    return {"feature": best, "name_score": best_score}


def geocode_project(project: dict, features: list[dict]) -> tuple[dict, dict]:
    result = dict(project)
    matches = {}
    for suffix in ("a", "b"):
        name = project.get(f"endpoint_{suffix}", "")
        match = match_endpoint(name, features, project["state"], project["utility"]) if name else None
        matches[suffix] = match
        coords = match["feature"]["geometry"]["coordinates"] if match else None
        result[f"lat_{suffix}"] = coords[1] if coords else ""
        result[f"lon_{suffix}"] = coords[0] if coords else ""
        result[f"osm_id_{suffix}"] = match["feature"]["properties"]["osm_id"] if match else ""
    points = [(result[f"lat_{s}"], result[f"lon_{s}"]) for s in ("a", "b") if result[f"lat_{s}"] != ""]
    result["lat_center"] = sum(point[0] for point in points) / len(points) if points else ""
    result["lon_center"] = sum(point[1] for point in points) / len(points) if points else ""
    return result, matches
