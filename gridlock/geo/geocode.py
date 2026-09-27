"""Cache OSM substations and match project endpoint names to them."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import requests
from rapidfuzz import fuzz

from overlap import haversine_miles, max_plausible_miles


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


ABBREVIATIONS = {"ST": "SAINT", "FT": "FORT", "MT": "MOUNT"}
GENERIC_TOKENS = {"NORTH", "SOUTH", "EAST", "WEST", "CENTER", "CENTRAL", "PRIMARY", "INDUSTRIAL", "PARK", "COUNTY", "CREEK"}
RELAXED_SCORE = 72


def normalize_name(value: str) -> str:
    value = re.sub(r"\([^)]*\)|#\s*\d+", " ", value.upper())
    value = re.sub(r"\b(?:SUBSTATION|SUB|PRIMARY|SAV)\b", " ", value)
    return " ".join(ABBREVIATIONS.get(token, token) for token in re.findall(r"[A-Z0-9]+", value))


def _distinctive(tokens: set[str]) -> bool:
    return any(len(token) >= 5 and token not in GENERIC_TOKENS for token in tokens)


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


def candidate_matches(name: str, features: list[dict], expected_state: str, utility: str, limit: int = 6) -> list[dict]:
    """Best-scoring OSM substations for a name, highest score first."""
    normalized = normalize_name(name)
    if not normalized:
        return []
    found = []
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
        if score >= MIN_NAME_SCORE:
            found.append({"feature": feature, "name_score": score})
    if not found:
        found = _relaxed_matches(normalized, features, expected_state, utility)
    found.sort(key=lambda item: -item["name_score"])
    return found[:limit]


def _relaxed_matches(normalized: str, features: list[dict], expected_state: str, utility: str) -> list[dict]:
    """Second pass: one name's words are all contained in the other (SALUDA vs SALUDA COUNTY).

    Scored below every strict match, and only on a distinctive shared word so that
    generic names such as NORTH cannot match NORTH DUBLIN.
    """
    query = set(normalized.split())
    found = []
    for feature in features:
        props = feature["properties"]
        if props.get("gridlock_state") != expected_state:
            continue
        candidate = set(normalize_name(props.get("name", "")).split())
        if not candidate or not (query <= candidate or candidate <= query):
            continue
        if _distinctive(query & candidate):
            found.append({"feature": feature, "name_score": RELAXED_SCORE, "relaxed": True})
    return found


def match_endpoint(name: str, features: list[dict], expected_state: str, utility: str) -> dict | None:
    found = candidate_matches(name, features, expected_state, utility, limit=1)
    return found[0] if found else None


SAVANNAH = (32.08, -81.09)
AREA_HINTS = {"SAV:": (SAVANNAH, 70)}


def _in_hint_area(project: dict, candidates: list[dict]) -> list[dict]:
    """Keep candidates near the area named by a project prefix (SAV: = Savannah); no-op if none qualify."""
    for prefix, ((lat, lon), radius) in AREA_HINTS.items():
        if project["project_name"].upper().startswith(prefix):
            near = [c for c in candidates
                    if haversine_miles(lat, lon, c["feature"]["geometry"]["coordinates"][1],
                                       c["feature"]["geometry"]["coordinates"][0]) <= radius]
            return near or candidates
    return candidates


def choose_pair(project: dict, cands_a: list[dict], cands_b: list[dict]) -> tuple[dict | None, dict | None]:
    """Pick the endpoint pair that forms a plausible line; fall back to the best names."""
    limit = max_plausible_miles(project)
    best = None
    for a in cands_a:
        for b in cands_b:
            if a["feature"] is b["feature"]:
                continue
            (lon_a, lat_a), (lon_b, lat_b) = a["feature"]["geometry"]["coordinates"], b["feature"]["geometry"]["coordinates"]
            sep = haversine_miles(lat_a, lon_a, lat_b, lon_b)
            plausible = sep <= limit
            key = (plausible, a["name_score"] + b["name_score"], -sep)
            if best is None or key > best[0]:
                best = (key, a, b)
    if best is None:
        return (cands_a[0] if cands_a else None), (cands_b[0] if cands_b else None)
    return best[1], best[2]


def _given_matches(project: dict) -> dict:
    """Endpoints the submitter located by coordinates: taken as-is, no name matching."""
    given = {}
    for suffix in ("a", "b"):
        lat, lon = project.get(f"given_lat_{suffix}"), project.get(f"given_lon_{suffix}")
        if lat in ("", None) or lon in ("", None):
            continue
        given[suffix] = {
            "feature": {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                "properties": {"osm_id": "submitted", "gridlock_state": project["state"]},
            },
            "name_score": 100,
            "given": True,
        }
    return given


def geocode_project(project: dict, features: list[dict], inferrer=None) -> tuple[dict, dict]:
    result = dict(project)
    cands = {}
    for suffix in ("a", "b"):
        name = project.get(f"endpoint_{suffix}", "")
        found = candidate_matches(name, features, project["state"], project["utility"]) if name else []
        cands[suffix] = _in_hint_area(project, found)
    for suffix, given_match in _given_matches(project).items():
        cands[suffix] = [given_match]
    both = bool(cands["a"] and cands["b"])
    for suffix in ("a", "b"):
        # An ambiguous relaxed match is only usable when the other endpoint can disambiguate it.
        if not both and len(cands[suffix]) > 1 and cands[suffix][0].get("relaxed"):
            cands[suffix] = []
    if cands["a"] and cands["b"]:
        matches = dict(zip(("a", "b"), choose_pair(project, cands["a"], cands["b"])))
    else:
        matches = {s: (cands[s][0] if cands[s] else None) for s in ("a", "b")}
    methods = {
        s: ("submitted_coordinates" if m.get("given") else "name_relaxed" if m.get("relaxed") else "name")
        for s, m in matches.items() if m
    }
    if inferrer is not None:
        matches, inferred = inferrer.infer(project, matches)
        methods.update(inferred)
    result["geocode_method"] = ";".join(f"{s}:{methods[s]}" for s in ("a", "b") if s in methods)
    for suffix in ("a", "b"):
        match = matches[suffix]
        coords = match["feature"]["geometry"]["coordinates"] if match else None
        result[f"lat_{suffix}"] = coords[1] if coords else ""
        result[f"lon_{suffix}"] = coords[0] if coords else ""
        result[f"osm_id_{suffix}"] = match["feature"]["properties"]["osm_id"] if match else ""
    points = [(result[f"lat_{s}"], result[f"lon_{s}"]) for s in ("a", "b") if result[f"lat_{s}"] != ""]
    result["lat_center"] = sum(point[0] for point in points) / len(points) if points else ""
    result["lon_center"] = sum(point[1] for point in points) / len(points) if points else ""
    return result, matches
