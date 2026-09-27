"""Parse Dominion Energy SC project pages (one project per page)."""
import re
from pathlib import Path

from .common import clamp_window, endpoints, iso_date, max_kv

_MILES = re.compile(r"(\d+(?:\.\d+)?)\s*miles?\b", re.I)
_MONEY = re.compile(r"\$\s*([\d,]+)")


def _lines(text):
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _after(lines, label, stop=None):
    """Lines following `label` until the next line that starts `stop`."""
    i = next(k for k, ln in enumerate(lines) if ln.startswith(label))
    out = []
    for ln in lines[i + 1:]:
        if stop and ln.startswith(stop):
            break
        out.append(ln)
    return out


SPEND_START = ["2023-01-01", "2024-01-01", "2025-01-01", "2026-01-01", "2027-01-01", "2028-01-01"]


def spend_start(cost_txt, in_service):
    """First day of the first budget year with spend (Previous = before 2024 -> 2023-01-01).

    Dominion gives no start date; the yearly spend table is the best evidence of when work begins.
    """
    amounts = [int(x.replace(",", "")) for x in _MONEY.findall(cost_txt)]
    for iso, amount in zip(SPEND_START, amounts[:6]):
        if amount > 0:
            return iso
    return f"{in_service[:4]}-01-01" if in_service else ""


def parse_page(text, source_file):
    lines = _lines(text)
    name = " ".join(_after(lines, "5 Year Budget", stop="Project ID"))
    pid = "".join(_after(lines, "Project ID", stop="Project Description")).replace(" ", "")
    desc = " ".join(_after(lines, "Project Description", stop="Project Need"))
    date_txt = " ".join(_after(lines, "Planned In-Service Date", stop="Estimated Project Cost"))
    cost_txt = " ".join(_after(lines, "Estimated Project Cost"))
    dollars = _MONEY.findall(cost_txt)
    m = _MILES.search(name) or _MILES.search(desc)
    a, b = endpoints(name)
    in_service = iso_date(date_txt)
    build_start, build_end = clamp_window(spend_start(cost_txt, in_service), in_service)
    return {
        "project_id": f"DESC_{pid}",
        "utility": "DESC",
        "state": "SC",
        "project_name": name,
        "endpoint_a": a,
        "endpoint_b": b,
        "voltage_kv": max_kv(name) or max_kv(desc),
        "project_type": "",
        "length_mi": float(m.group(1)) if m else None,
        "est_cost_usd": int(dollars[-1].replace(",", "")) if dollars else None,
        "start_date": "",
        "in_service_date": in_service,
        "build_start": build_start,
        "build_end": build_end,
        "source_file": source_file,
        "source_ref": lines[0],
    }


def parse_all(pages_dir):
    pages = sorted(Path(pages_dir).glob("*.txt"), key=lambda p: int(p.stem))
    return [
        parse_page(p.read_text(encoding="utf-8"), f"desc_pages/{p.name}") for p in pages
    ]
