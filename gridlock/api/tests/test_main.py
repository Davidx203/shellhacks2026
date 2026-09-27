import sqlite3

import pytest
from fastapi.testclient import TestClient

from api import main


def seed_db(path):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE projects (project_id TEXT, utility TEXT, length_mi TEXT, voltage_kv TEXT,
                     est_cost_usd TEXT, lat_center TEXT, lon_center TEXT, confidence TEXT, human_verified TEXT)""")
    conn.execute("INSERT INTO projects VALUES ('GPC_1','GPC','10','230','','32.3','-81.1','0.9','false')")
    conn.execute("INSERT INTO projects VALUES ('DESC_1','DESC','3','230','5000000','32.31','-81.11','0.8','false')")
    conn.execute("""CREATE TABLE overlaps (overlap_id TEXT, project_id_gpc TEXT, project_id_desc TEXT,
                     distance_mi TEXT, time_gap_days TEXT, rank TEXT)""")
    conn.execute("INSERT INTO overlaps VALUES ('OVL_1','GPC_1','DESC_1','3.0','100','1')")
    conn.execute("INSERT INTO overlaps VALUES ('OVL_99','GPC_1','DESC_1','9.0','40','99')")   # beyond any precomputed brief
    conn.execute("""CREATE TABLE briefs (overlap_id TEXT, shared_corridor_mi TEXT, row_width_ft TEXT,
                     shared_acres TEXT, land_cost_per_acre_usd TEXT, est_land_savings_usd TEXT, assumptions_note TEXT)""")
    conn.execute("INSERT INTO briefs VALUES ('OVL_1','3.0','150','10.33','10000','103306','precomputed note')")
    conn.commit()
    conn.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "gridlock.db"
    seed_db(db_path)
    monkeypatch.setattr(main, "DB_PATH", db_path)
    return TestClient(main.app)


def test_brief_uses_the_real_voltage_aware_formula_not_the_fixture_placeholder(client):
    body = client.get("/briefs/OVL_1").json()
    assert body["row_width_ft"] == 150               # from 230 kV, not the old hardcoded 100
    assert body["shared_corridor_mi"] == 3            # the shorter project's length, not a hardcoded 5
    expected_acres = 3 * 5280 * 150 / 43560
    assert body["shared_acres"] == round(expected_acres, 2)
    assert body["est_land_savings_usd"] == round(expected_acres * 10000)
    assert "$5,000,000" in body["assumptions_note"]


def test_brief_overrides_change_the_real_numbers(client):
    body = client.get("/briefs/OVL_1?shared_mi=6&cost_per_acre=20000").json()
    assert body["shared_corridor_mi"] == 6 and body["land_cost_per_acre_usd"] == 20000
    assert body["row_width_ft"] == 150                # width still voltage-based, not overridden
    expected_acres = 6 * 5280 * 150 / 43560
    assert body["shared_acres"] == round(expected_acres, 2)
    assert body["est_land_savings_usd"] == round(expected_acres * 20000)


def test_brief_works_for_an_overlap_with_no_precomputed_row(client):
    body = client.get("/briefs/OVL_99").json()
    assert body["overlap_id"] == "OVL_99" and body["shared_corridor_mi"] == 3


def test_brief_404_for_unknown_overlap(client):
    assert client.get("/briefs/OVL_missing").status_code == 404


def test_narrative_mentions_the_estimated_savings(client):
    body = client.post("/briefs/OVL_1/narrative").json()
    assert "$" in body["narrative"]
