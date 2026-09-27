"""Build windows and how two projects' windows relate."""

from __future__ import annotations

from datetime import date


def build_window(project: dict) -> tuple[date, date] | None:
    """(start, end) from build_start/build_end, falling back to start_date/in_service_date."""
    end = project.get("build_end") or project.get("in_service_date")
    if not end:
        return None
    start = project.get("build_start") or project.get("start_date") or end
    return date.fromisoformat(min(start, end)), date.fromisoformat(end)


def window_relation(a: dict, b: dict) -> dict:
    """windows_overlap, overlap_days, and window_gap_days (0 when they overlap)."""
    wa, wb = build_window(a), build_window(b)
    if not wa or not wb:
        return {"windows_overlap": False, "overlap_days": 0, "window_gap_days": None, "shorter_days": None}
    latest_start, earliest_end = max(wa[0], wb[0]), min(wa[1], wb[1])
    overlap = latest_start <= earliest_end
    return {
        "windows_overlap": overlap,
        "overlap_days": (earliest_end - latest_start).days if overlap else 0,
        "window_gap_days": 0 if overlap else (latest_start - earliest_end).days,
        "shorter_days": min((wa[1] - wa[0]).days, (wb[1] - wb[0]).days),
    }
