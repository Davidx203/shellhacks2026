"""preview -> commit -> merge -> projects_raw, with the rebuild run in-process."""
import csv

import pymupdf
import pytest
from fastapi.testclient import TestClient

from api import submissions
from api.main import app
from pipeline import build_raw
from pipeline.common import COLUMNS

DESC_PAGE = """Project 43 of 44
Dominion Energy South Carolina
5 Year Budget
Urquhart - Aiken PSA 46 kV: Rebuild
Project ID
6810 O
Project Description
Rebuilding the section of 46 kV line. 4.5 miles.
Project Need
System hardening
Project Status
Planned
Planned In-Service Date
06/30/2028
Estimated Project Cost
Previous
2024
2025
2026
2027
2028
Total*
$0
$0
$0
$0
$0
$3,000,000
$3,000,000
"""


class InProcessRebuilder:
    def __init__(self, baseline, submissions_path, out):
        self.baseline, self.submissions_path, self.out = baseline, submissions_path, out
        self.count = 0

    def request(self):
        rows = build_raw.build(raw=self.out.parent / "no-report-text", baseline=self.baseline, submissions=self.submissions_path)
        build_raw.write(rows, self.out)
        self.count += 1
        return f"job-{self.count}"

    def status(self, job_id):
        return {"status": "done", "message": ""}


def read_out(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["project_id"]: row for row in csv.DictReader(handle)}


@pytest.fixture
def world(tmp_path, monkeypatch):
    baseline = tmp_path / "projects_report.csv"
    row = dict.fromkeys(COLUMNS, "")
    row.update(project_id="DESC_6810O", utility="DESC", state="SC", project_name="Urquhart - Aiken PSA 46 kV: Rebuild",
               endpoint_a="Urquhart", endpoint_b="Aiken PSA", voltage_kv="46", project_type="rebuild", length_mi="4.5",
               est_cost_usd="3000000", in_service_date="2027-12-31", build_start="2027-01-01", build_end="2027-12-31")
    with baseline.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    out, log = tmp_path / "projects_raw.csv", tmp_path / "submissions.csv"
    rebuilder = InProcessRebuilder(baseline, log, out)
    rebuilder.request()                                    # the state before any submission
    monkeypatch.setattr(submissions, "SUBMISSIONS_PATH", log)
    monkeypatch.setattr(submissions, "RAW_PROJECTS_PATH", out)
    monkeypatch.setattr(submissions, "rebuilder", rebuilder)
    return TestClient(app), out


def pdf_bytes():
    doc = pymupdf.open()
    doc.new_page().insert_text((36, 40), DESC_PAGE, fontsize=7)
    data = doc.tobytes()
    doc.close()
    return data


def test_pdf_update_then_reject_restores_the_report_value(world):
    client, out = world
    assert read_out(out)["DESC_6810O"]["in_service_date"] == "2027-12-31"
    preview = client.post("/submissions/preview/pdf", data={"utility": "DESC"}, files={"file": ("r.pdf", pdf_bytes(), "application/pdf")}).json()
    assert preview["rows"][0]["status"] == "update"
    body = {"utility": "DESC", "origin": "pdf", "submitted_by": "Ana", "rows": [preview["rows"][0]["row"]]}
    assert client.post("/submissions/commit", json=body).status_code == 200

    row = read_out(out)["DESC_6810O"]
    assert row["in_service_date"] == "2028-06-30" and row["origin"] == "pdf" and row["project_name"].startswith("Urquhart")
    assert row["est_cost_usd"] == "3000000" and row["submitted_by"] == "Dominion Energy SC (Ana)"

    again = client.post("/submissions/preview/pdf", data={"utility": "DESC"}, files={"file": ("r.pdf", pdf_bytes(), "application/pdf")}).json()
    assert again["rows"][0]["status"] == "unchanged"                       # double submit is harmless
    assert client.post("/submissions/commit", json={**body, "rows": [again["rows"][0]["row"]]}).status_code == 422

    submission_id = client.get("/submissions").json()[0]["submission_id"]
    client.post(f"/submissions/{submission_id}/reject")
    restored = read_out(out)["DESC_6810O"]
    assert restored["in_service_date"] == "2027-12-31" and restored["origin"] == "report"


def test_manual_form_adds_a_new_project_with_its_coordinates(world):
    client, out = world
    form = {"utility": "GPC", "project_name": "Okatie - Bluffton 115kV: Rebuild", "endpoint_a": "Okatie",
            "endpoint_b": "Bluffton", "in_service_date": "2029-03-01", "lat_a": "32.2776", "lon_a": "-80.9686"}
    entry = client.post("/submissions/preview/form", json=form).json()["rows"][0]
    assert entry["status"] == "new" and entry["errors"] == []
    client.post("/submissions/commit", json={"utility": "GPC", "origin": "form", "submitted_by": "", "rows": [entry["row"]]})
    row = read_out(out)["GPC_SUB1"]
    assert row["origin"] == "form" and row["state"] == "GA" and row["given_lat_a"] == "32.2776"
    assert row["build_start"] == "2029-01-01" and row["build_end"] == "2029-03-01"
