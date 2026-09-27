"""Infer endpoints that have no name match, from same-voltage routes and town locations."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from geocode import OPERATORS, _annotate_states, max_plausible_miles
from overlap import haversine_miles

DATA = Path(__file__).resolve().parents[1] / "data"
ALL_SUBSTATIONS_CACHE = DATA / "cache" / "substations_all_ga_sc.geojson"
PLACES_CACHE = DATA / "cache" / "places_ga_sc.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
STATE_NAMES = {"GA": "Georgia", "SC": "South Carolina"}
ALL_QUERY = '[out:json][timeout:120];nwr["power"="substation"](30.3,-85.7,35.3,-78.5);out center tags;'
INFERRED_NAME_SCORE = 35
PLACE_RADIUS_MI = 6.0
MIN_SCORE = 0.55
MIN_MARGIN = 0.12
OPERATOR_BONUS = 0.15
UNREACHABLE_FACTOR = 0.85
TIE_MI = 0.3
FRIENDLY_OPERATORS = {"GPC": ("GEORGIA TRANSMISSION", "MEAG", "MUNICIPAL ELECTRIC"), "DESC": ()}


def fetch_all_substations(cache: Path = ALL_SUBSTATIONS_CACHE) -> list[dict] | None:
    """Every OSM substation, named or not, with GA/SC annotation; None if unavailable."""
    if cache.exists():
        return _annotate_states(json.loads(cache.read_text(encoding="utf-8"))["features"], cache)
    from geocode import FALLBACK_URL, OVERPASS_URL
    for url in (OVERPASS_URL, FALLBACK_URL):
        try:
            response = requests.post(url, data={"data": ALL_QUERY}, timeout=170,
                                     headers={"User-Agent": "GridlockRadar/1.0 (single cached research query)"})
            response.raise_for_status()
            elements = response.json()["elements"]
        except (requests.RequestException, ValueError, KeyError):
            continue
        features = []
        for item in elements:
            point = item.get("center", item)
            if "lat" not in point or "lon" not in point:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [point["lon"], point["lat"]]},
                "properties": {**item.get("tags", {}), "osm_id": f'{item["type"]}/{item["id"]}'},
            })
        if features:
            cache.parent.mkdir(parents=True, exist_ok=True)
            return _annotate_states(features, cache)
    return None


class PlaceLookup:
    """Town-level locations from Nominatim, cached on disk so reruns and teammates need no network."""

    def __init__(self, cache: Path = PLACES_CACHE, online: bool = True):
        self.cache_path = cache
        self.cache = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
        self.online = online
        self.dirty = False

    def __call__(self, name: str, state: str):
        key = f"{name.upper()}|{state}"
        if key in self.cache:
            hit = self.cache[key]
            return tuple(hit) if hit else None
        if not self.online:
            return None
        try:
            response = requests.get(NOMINATIM_URL, timeout=30, headers={"User-Agent": "GridlockRadar/1.0 (hackathon research)"},
                                    params={"q": f"{name}, {STATE_NAMES[state]}", "format": "json", "limit": 1,
                                            "countrycodes": "us", "featuretype": "settlement"})
            response.raise_for_status()
            results = response.json()
        except (requests.RequestException, ValueError):
            return None
        time.sleep(1.1)
        hit = [float(results[0]["lat"]), float(results[0]["lon"])] if results else None
        self.cache[key] = hit
        self.dirty = True
        return tuple(hit) if hit else None

    def save(self) -> None:
        if self.dirty:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, indent=0, sort_keys=True), encoding="utf-8")


def _kvs(props: dict) -> set[int]:
    return {int(v) // 1000 for v in re.findall(r"\d+", props.get("voltage", "")) if int(v) >= 1000}


def _operator_ok(props: dict, utility: str) -> bool:
    operator = (props.get("operator") or "").upper()
    return not operator or any(token in operator for token in OPERATORS[utility] + FRIENDLY_OPERATORS[utility])


class Inferrer:
    def __init__(self, substations: list[dict], grid, place_lookup):
        self.subs = [
            (f, f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0], _kvs(f["properties"]))
            for f in substations
        ]
        self.grid = grid
        self.place_lookup = place_lookup

    def infer(self, project: dict, matches: dict) -> tuple[dict, dict]:
        matches, methods = dict(matches), {}
        kv = int(project["voltage_kv"]) if str(project.get("voltage_kv") or "").isdigit() else 0
        for side in ("a", "b"):
            name = project.get(f"endpoint_{side}", "")
            if matches.get(side) or not name:
                continue
            other = matches.get("b" if side == "a" else "a")
            found = self._infer_side(project, name, kv, other)
            if found:
                matches[side], methods[side] = found
        return matches, methods

    def _infer_side(self, project, name, kv, other):
        place = self.place_lookup(name, project["state"])
        source = None
        if other and self.grid is not None and kv:
            lon, lat = other["feature"]["geometry"]["coordinates"]
            source = (lat, lon)
        stated = float(project["length_mi"]) if project.get("length_mi") else None
        limit = max_plausible_miles(project)
        if place and source and haversine_miles(*place, *source) > limit + PLACE_RADIUS_MI:
            place = None        # a same-named town elsewhere; it contradicts the located end of the line
        dist = self.grid.distances_from(kv, source, limit) if source else {}
        if not place and not dist:
            return None

        scored = []
        for feature, lat, lon, kvs in self.subs:
            props = feature["properties"]
            if kv and not dist and kv not in kvs:
                continue        # OSM voltage tags are incomplete; with a line route the route itself proves the fit
            if props.get("gridlock_state") != project["state"] or not _operator_ok(props, project["utility"]):
                continue
            terms, factor = [], 1.0
            if place:
                terms.append(max(0.0, 1 - haversine_miles(*place, lat, lon) / PLACE_RADIUS_MI))
            if dist:
                route = self.grid.distance_to(kv, dist, (lat, lon))
                if route is None or route < 0.2:
                    if not place:
                        continue
                    factor = UNREACHABLE_FACTOR      # the OSM line network may simply have a gap here
                elif stated:
                    terms.append(max(0.0, 1 - abs(route - stated) / stated))
                else:
                    terms.append(max(0.0, 1 - route / limit) * 0.7)
            if not terms or (len(terms) > 1 and min(terms) <= 0):
                continue
            operator = (props.get("operator") or "").upper()
            bonus = OPERATOR_BONUS if operator and any(t in operator for t in OPERATORS[project["utility"]]) else 0.0
            scored.append((sum(terms) / len(terms) * factor + bonus, len(terms), lat, lon, feature))
        if not scored:
            return None
        scored.sort(key=lambda item: -item[0])
        best = scored[0]
        rivals = [s for s in scored[1:] if haversine_miles(best[2], best[3], s[2], s[3]) > TIE_MI]
        if best[0] < MIN_SCORE or (rivals and best[0] - rivals[0][0] < MIN_MARGIN):
            return None
        method = "inferred_" + ("route+place" if place and dist else "place" if place else "route")
        return {"feature": best[4], "name_score": INFERRED_NAME_SCORE, "inferred": True}, method
