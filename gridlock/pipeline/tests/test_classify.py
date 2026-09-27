import pytest

from pipeline.classify import classify


@pytest.mark.parametrize("name,expected", [
    ("Harleyville 115KV Transmission Tap – Construct (1.4 miles)", "new_line"),
    ("Jasper – Okatie 230 kV #2: Construct", "new_line"),
    ("Cainhoy - Hamlin 115kV: Rebuild Line and Cainhoy – Hamlin 115 kV #2: Construct New 115 kV Line", "new_line"),
    ("Okatie-Bluffton 115kV: Rebuild", "rebuild"),
    ("SAV: GOSHEN (SAV) - MCINTOSH 115KV LINE REBUILD", "rebuild"),
    ("FOO - BAR 115KV RECONDUCTOR", "reconductor"),
    ("SCOTTDALE RELAY MODERNIZATION", "relay"),
    ("THALMANN AND COLERAIN 230 KV LINE RELAY PANEL UPGRADES", "relay"),
    ("SAV: MCINTOSH - PURRYSBURG 230KV REACTORS", "substation"),
    ("ANTHONY SHOALS STATCOM SYSTEM", "substation"),
    ("Goose Creek Reservoir: Line Crossings", "other"),
    ("NEWTON 115KV UPGRADE", "other"),
    ("DRESDEN LINE PROTECTIVE RELAYING", "relay"),
    ("GTC: ROBINS SPRING CAPACITOR BANK INSTALLATION", "substation"),
    ("GTC: RIDDLEVILLE BUS REPLACEMENT", "substation"),
    ("OHARA BREAKER REPLACEMENT", "substation"),
    ("CC - EAST VILLA RICA AREA SWITCHING STATION (CC IMPROVEMENT)", "substation"),
    ("ANNISTON - HAMMOND 230KV LINE", "other"),
    ("NEWBERRY - FOO 115KV REBUILD", "rebuild"),
])
def test_classify(name, expected):
    assert classify(name) == expected


from pipeline.classify import finalize_row


def test_finalize_row_sets_type_and_clears_endpoint_b_for_relay():
    relay = finalize_row({"project_name": "SCOTTDALE RELAY MODERNIZATION", "endpoint_b": "X"})
    assert relay["project_type"] == "relay" and relay["endpoint_b"] == ""
    line = finalize_row({"project_name": "OKATIE - BLUFFTON 115KV REBUILD", "endpoint_b": "BLUFFTON"})
    assert line["project_type"] == "rebuild" and line["endpoint_b"] == "BLUFFTON"
