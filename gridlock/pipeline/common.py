"""Helpers shared by the DESC and GPC parsers."""
import re
from datetime import datetime

COLUMNS = [
    "project_id", "utility", "state", "project_name", "endpoint_a", "endpoint_b",
    "voltage_kv", "project_type", "length_mi", "est_cost_usd", "start_date",
    "in_service_date", "build_start", "build_end", "source_file", "source_ref",
]
RAW_EXTRA = [
    "origin", "submission_id", "submitted_by", "submitted_at",
    "given_lat_a", "given_lon_a", "given_lat_b", "given_lon_b",
]
RAW_COLUMNS = COLUMNS + RAW_EXTRA

_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b")
_KV = re.compile(r"(\d+(?:\.\d+)?)(?:\s*[-/]\s*(\d+(?:\.\d+)?))*\s*kv\b", re.I)
_NUM = re.compile(r"\d+(?:\.\d+)?")
_DASH = re.compile(r"\s*[–—-]\s*")
_PREFIX = re.compile(r"^(?:(?:SAV|GTC|MEAG|DU|CC|GRID)\s*[:-]\s*)+", re.I)
_TAIL_WORDS = {
    "RELAY", "RELAYING", "BUS", "BREAKER", "STATCOM", "REACTOR", "REACTORS",
    "MODERNIZATION", "REPLACEMENT", "INSTALLATION", "AREA", "SOLUTION", "PROJECT",
    "IMPROVEMENT", "IMPROVEMENTS", "UPGRADE", "UPGRADES", "BANK", "AUTO", "NEW",
    "SMART", "SWITCHING", "LINE", "PROTECTIVE", "CAP", "XFMR", "SUBSTATION",
    "TRANSMISSION", "AND", "&",
}


def fix_kv_typos(text):
    """`23O KV` (letter O for zero) -> `230 KV`."""
    return re.sub(r"(?<=\d)O(?=\d*\s*kv\b)", "0", text, flags=re.I)


def iso_date(text):
    """First M/D/YY or M/D/YYYY date in text -> YYYY-MM-DD, or '' if none."""
    m = _DATE.search(text or "")
    if not m:
        return ""
    mo, d, y = m.groups()
    fmt = "%m/%d/%y" if len(y) == 2 else "%m/%d/%Y"
    return datetime.strptime(f"{mo}/{d}/{y}", fmt).strftime("%Y-%m-%d")


def clamp_window(start_iso, end_iso):
    """(build_start, build_end) with start never after end; blank end means no window."""
    if not end_iso:
        return "", ""
    if not start_iso:
        start_iso = end_iso
    return min(start_iso, end_iso), end_iso


def max_kv(text):
    """Highest voltage mentioned (`230-115KV`, `230 KV`, `23O KV`), or None."""
    volts = [
        float(n)
        for m in _KV.finditer(fix_kv_typos(text or ""))
        for n in _NUM.findall(m.group(0))
    ]
    return int(max(volts)) if volts else None


def _clean_segment(seg):
    """Trim trailing equipment words/numbers (never the first word) and `#N` marks."""
    words = re.sub(r"\s*#\s*\d+", "", seg).split()
    for i, w in enumerate(words[1:], 1):
        if w.upper() in _TAIL_WORDS or w[0].isdigit():
            words = words[:i]
            break
    return " ".join(words)


def endpoints(name):
    """(endpoint_a, endpoint_b) from the text before the first voltage or colon."""
    text = _PREFIX.sub("", re.sub(r"\([^)]*\)", " ", fix_kv_typos(name)))
    cut = len(text)
    m = _KV.search(text)
    if m:
        cut = min(cut, m.start())
    if ":" in text:
        cut = min(cut, text.index(":"))
    parts = [_clean_segment(p) for p in _DASH.split(text[:cut]) if p.strip()]
    parts = [p for p in parts if p]
    a = parts[0] if parts else ""
    b = parts[1] if len(parts) > 1 else ""
    return a, b
