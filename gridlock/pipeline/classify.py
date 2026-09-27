import re

_RULES = [
    ("relay", r"\bRELAY\w*|\bMODERNIZATION\b|\bPANELS?\b"),
    ("new_line", r"\bCONSTRUCT\b|\bNEW\b|#\s*2\b"),
    ("rebuild", r"\bREBUILD\b|\bREBLD\b"),
    ("reconductor", r"\bRECONDUCTOR\w*"),
    ("substation", r"\bTRANSFORMERS?\b|\bREACTORS?\b|\bSTATCOM\b|\bSUB(?:STATION)?\b|\bAUTO ?BANKS?\b"
    r"|\bBANKS?\b|\bCAP(?:ACITOR)?\b|\bBREAKERS?\b|\bBUS(?:ES)?\b|\bSWITCHING\b|\bSTATION\b|\bVALVES?\b"),
]


def classify(name):
    """Keyword-based project_type; first matching rule wins (see plan precedence)."""
    for label, pattern in _RULES:
        if re.search(pattern, name, re.I):
            return label
    return "other"


def finalize_row(row):
    """Set project_type from the name; relay projects are single-site, so endpoint_b is cleared."""
    row["project_type"] = classify(row["project_name"])
    if row["project_type"] == "relay":
        row["endpoint_b"] = ""
    return row
