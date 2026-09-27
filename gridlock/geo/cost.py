"""Directional land savings estimates for the highest-ranked overlaps."""

from __future__ import annotations


WIDTH_BY_KV = {46: 50, 115: 100, 230: 150, 500: 200}
LAND_COST_PER_ACRE_USD = 10_000


def make_brief(
    overlap: dict,
    projects_by_id: dict[str, dict],
    shared_mi: float | None = None,
    land_cost_per_acre_usd: int | None = None,
) -> dict:
    """Directional land-savings estimate. `shared_mi` and `land_cost_per_acre_usd` let a caller
    (the UI's adjustable sliders) override the assumed corridor length and land cost; the
    right-of-way width always comes from voltage, since that is not something to guess at."""
    projects = [projects_by_id[overlap["project_id_gpc"]], projects_by_id[overlap["project_id_desc"]]]
    lengths = [float(p["length_mi"]) for p in projects if p.get("length_mi")]
    given_mi = shared_mi is not None
    if given_mi:
        shared_mi = float(shared_mi)
    else:
        shared_mi = min(min(lengths), 5.0) if len(lengths) == 2 else 2.0
    voltages = [float(p["voltage_kv"]) for p in projects if p.get("voltage_kv")]
    if voltages:
        reference_voltage = max(voltages)
        nearest = min(WIDTH_BY_KV, key=lambda kv: (abs(kv - reference_voltage), -kv))
        width = WIDTH_BY_KV[nearest]
        width_note = f"Assumed {width} ft right-of-way width from the nearest standard voltage ({nearest} kV) to the higher listed project voltage ({reference_voltage:g} kV)."
    else:
        width = 100
        width_note = "Assumed 100 ft right-of-way width because neither project has a voltage."
    cost_per_acre = LAND_COST_PER_ACRE_USD if land_cost_per_acre_usd is None else int(land_cost_per_acre_usd)
    acres = shared_mi * 5280 * width / 43560
    savings = round(acres * cost_per_acre)
    if given_mi:
        length_note = f"Used {shared_mi:g} shared corridor miles and ${cost_per_acre:,} per acre because those were given, not assumed."
    elif len(lengths) == 2:
        length_note = f"Assumed {shared_mi:g} shared corridor miles from the shorter stated project length, capped at 5 miles. Assumed land cost is ${cost_per_acre:,} per acre."
    else:
        length_note = f"Assumed 2 shared corridor miles because at least one project lacks a stated length. Assumed land cost is ${cost_per_acre:,} per acre."
    desc_cost = projects[1].get("est_cost_usd")
    context = f" DESC project budget is ${int(float(desc_cost)):,}; it is context, not included in estimated savings." if desc_cost else ""
    note = (f"{length_note} {width_note} "
            "This directional estimate assumes the projects could share the entire stated corridor; "
            "center-point proximity alone does not prove a shared route or land acquisition savings." + context)
    return {
        "overlap_id": overlap["overlap_id"],
        "shared_corridor_mi": shared_mi,
        "row_width_ft": width,
        "shared_acres": round(acres, 2),
        "land_cost_per_acre_usd": cost_per_acre,
        "est_land_savings_usd": savings,
        "assumptions_note": note,
    }
