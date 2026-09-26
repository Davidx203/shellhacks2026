"""Directional land savings estimates for the highest-ranked overlaps."""

from __future__ import annotations


WIDTH_BY_KV = {46: 50, 115: 100, 230: 150, 500: 200}
LAND_COST_PER_ACRE_USD = 10_000


def make_brief(overlap: dict, projects_by_id: dict[str, dict]) -> dict:
    projects = [projects_by_id[overlap["project_id_gpc"]], projects_by_id[overlap["project_id_desc"]]]
    lengths = [float(p["length_mi"]) for p in projects if p.get("length_mi")]
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
    acres = shared_mi * 5280 * width / 43560
    savings = round(acres * LAND_COST_PER_ACRE_USD)
    length_note = (
        f"Assumed {shared_mi:g} shared corridor miles from the shorter stated project length, capped at 5 miles."
        if len(lengths) == 2 else "Assumed 2 shared corridor miles because at least one project lacks a stated length."
    )
    desc_cost = projects[1].get("est_cost_usd")
    context = f" DESC project budget is ${int(float(desc_cost)):,}; it is context, not included in estimated savings." if desc_cost else ""
    note = (f"{length_note} {width_note} Assumed land cost is ${LAND_COST_PER_ACRE_USD:,} per acre. "
            "This directional estimate assumes the projects could share the entire stated corridor; "
            "center-point proximity alone does not prove a shared route or land acquisition savings." + context)
    return {
        "overlap_id": overlap["overlap_id"],
        "shared_corridor_mi": shared_mi,
        "row_width_ft": width,
        "shared_acres": round(acres, 2),
        "land_cost_per_acre_usd": LAND_COST_PER_ACRE_USD,
        "est_land_savings_usd": savings,
        "assumptions_note": note,
    }
