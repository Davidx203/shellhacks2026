"""Route a project's two endpoints along real same-voltage OSM power lines."""

from __future__ import annotations

import collections
import heapq
import json
import re
from pathlib import Path

import requests

from geocode import FALLBACK_URL, OVERPASS_URL
from overlap import haversine_miles

DATA = Path(__file__).resolve().parents[1] / "data"
LINES_CACHE = DATA / "cache" / "power_lines_ga_sc.json"
LINES_QUERY = ('[out:json][timeout:150];way["power"="line"]["voltage"~"(46|69|115|138|161|230|500)000"]'
               "(30.3,-85.7,35.3,-78.5);out tags geom;")
BRIDGE_MI = 0.15
SNAP_MI = 0.8
CELL = 0.005


def fetch_power_lines(cache: Path = LINES_CACHE) -> list[dict] | None:
    """Local snapshot after the first successful Overpass request; None if unavailable."""
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["elements"]
    for url in (OVERPASS_URL, FALLBACK_URL):
        try:
            response = requests.post(url, data={"data": LINES_QUERY}, timeout=170,
                                     headers={"User-Agent": "GridlockRadar/1.0 (single cached research query)"})
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue
        if payload.get("elements"):
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload), encoding="utf-8")
            return payload["elements"]
    return None


def _voltages_kv(tags: dict) -> set[int]:
    return {int(v) // 1000 for v in re.findall(r"\d+", tags.get("voltage", "")) if int(v) >= 1000}


class PowerGrid:
    def __init__(self, ways: list[dict]):
        self.by_kv: dict[int, list[list[tuple[float, float]]]] = collections.defaultdict(list)
        for way in ways:
            coords = [(p["lat"], p["lon"]) for p in way.get("geometry", [])]
            if len(coords) < 2:
                continue
            for kv in _voltages_kv(way.get("tags", {})):
                self.by_kv[kv].append(coords)
        self._graphs: dict[int, tuple[dict, dict]] = {}

    def _graph(self, kv: int) -> tuple[dict, dict]:
        if kv in self._graphs:
            return self._graphs[kv]
        adj: dict = collections.defaultdict(list)
        cells: dict = collections.defaultdict(list)
        for way in self.by_kv.get(kv, []):
            for a, b in zip(way, way[1:]):
                d = haversine_miles(*a, *b)
                adj[a].append((b, d))
                adj[b].append((a, d))
        for node in adj:
            cells[(round(node[0] / CELL), round(node[1] / CELL))].append(node)
        for node in list(adj):
            cy, cx = round(node[0] / CELL), round(node[1] / CELL)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    for other in cells.get((cy + dy, cx + dx), ()):
                        if other != node:
                            d = haversine_miles(*node, *other)
                            if d <= BRIDGE_MI:
                                adj[node].append((other, d))
        self._graphs[kv] = (adj, cells)
        return self._graphs[kv]

    def _nearest(self, cells: dict, point: tuple[float, float]) -> tuple[float, float] | None:
        cy, cx = round(point[0] / CELL), round(point[1] / CELL)
        best, best_d = None, SNAP_MI
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                for node in cells.get((cy + dy, cx + dx), ()):
                    d = haversine_miles(*point, *node)
                    if d < best_d:
                        best, best_d = node, d
        return best

    def distances_from(self, kv: int, point: tuple[float, float], cutoff: float) -> dict:
        """Miles along `kv` lines from `point` to every reachable node within cutoff (empty if none)."""
        if kv not in self.by_kv:
            return {}
        adj, cells = self._graph(kv)
        start = self._nearest(cells, point)
        if not start:
            return {}
        dist = {start: 0.0}
        queue = [(0.0, start)]
        while queue:
            d, node = heapq.heappop(queue)
            if d > dist.get(node, float("inf")) or d > cutoff:
                continue
            for nxt, w in adj[node]:
                nd = d + w
                if nd < dist.get(nxt, float("inf")) and nd <= cutoff:
                    dist[nxt] = nd
                    heapq.heappush(queue, (nd, nxt))
        return dist

    def distance_to(self, kv: int, dist: dict, point: tuple[float, float]) -> float | None:
        """Route miles from the source of `dist` to `point`, entering the line network within SNAP_MI."""
        if kv not in self.by_kv or not dist:
            return None
        _, cells = self._graph(kv)
        cy, cx = round(point[0] / CELL), round(point[1] / CELL)
        best = None
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                for node in cells.get((cy + dy, cx + dx), ()):
                    if node in dist:
                        gap = haversine_miles(*point, *node)
                        if gap <= SNAP_MI and (best is None or dist[node] + gap < best):
                            best = dist[node] + gap
        return best

    def route(self, kv: int, a: tuple[float, float], b: tuple[float, float], cutoff: float):
        """(miles, [(lat, lon), ...]) along lines of `kv`, or None when no route within cutoff."""
        if kv not in self.by_kv:
            return None
        adj, cells = self._graph(kv)
        start, goal = self._nearest(cells, a), self._nearest(cells, b)
        if not start or not goal:
            return None
        dist, prev = {start: 0.0}, {}
        queue = [(0.0, start)]
        while queue:
            d, node = heapq.heappop(queue)
            if node == goal:
                path = [node]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                return d, [a] + path[::-1] + [b]
            if d > dist.get(node, float("inf")) or d > cutoff:
                continue
            for nxt, w in adj[node]:
                nd = d + w
                if nd < dist.get(nxt, float("inf")):
                    dist[nxt], prev[nxt] = nd, node
                    heapq.heappush(queue, (nd, nxt))
        return None


def attach_routes(projects: list[dict], grid: PowerGrid) -> list[dict]:
    """Set route_mi on every project and return GeoJSON features for the routes found."""
    features = []
    for project in projects:
        project["route_mi"] = ""
        kv = int(project["voltage_kv"]) if str(project.get("voltage_kv") or "").isdigit() else 0
        if not (kv and project["lat_a"] != "" and project["lat_b"] != ""):
            continue
        a = (float(project["lat_a"]), float(project["lon_a"]))
        b = (float(project["lat_b"]), float(project["lon_b"]))
        straight = haversine_miles(*a, *b)
        found = grid.route(kv, a, b, cutoff=max(30.0, straight * 2.5 + 10))
        if not found:
            continue
        miles, coords = found
        project["route_mi"] = round(miles, 2)
        features.append({
            "type": "Feature",
            "properties": {"project_id": project["project_id"], "route_mi": round(miles, 2)},
            "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in coords]},
        })
    return features
