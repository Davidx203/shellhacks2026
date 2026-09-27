import csv
import threading

import pymupdf
import pytest
from fastapi.testclient import TestClient

from api import submissions
from api.main import app
from pipeline.common import RAW_COLUMNS

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
12/31/2027
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
$3,000,000
$0
$3,000,000
"""

FORM = {"utility": "GPC", "project_name": "Okatie - Bluffton 115kV: Rebuild", "endpoint_a": "Okatie",
        "endpoint_b": "Bluffton", "voltage_kv": "115", "in_service_date": "2026-06-01"}


class FakeRebuilder:
    def __init__(self):
        self.requests = 0

    def request(self):
        self.requests += 1
        return f"job-{self.requests}"

    def status(self, job_id):
        return {"status": "done", "message": ""} if job_id.startswith("job-") else None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(submissions, "SUBMISSIONS_PATH", tmp_path / "submissions.csv")
    monkeypatch.setattr(submissions, "RAW_PROJECTS_PATH", tmp_path / "projects_raw.csv")
    monkeypatch.setattr(submissions, "rebuilder", FakeRebuilder())
    return TestClient(app)


def make_pdf(text):
    doc = pymupdf.open()
    doc.new_page().insert_text((36, 40), text, fontsize=7)
    data = doc.tobytes()
    doc.close()
    return data


def write_current(path, **row):
    base = dict.fromkeys(RAW_COLUMNS, "")
    base.update(project_id="DESC_6810O", utility="DESC", state="SC", project_name="Urquhart - Aiken PSA 46 kV: Rebuild",
                endpoint_a="Urquhart", endpoint_b="Aiken PSA", voltage_kv="46", project_type="rebuild",
                length_mi="4.5", est_cost_usd="3000000", in_service_date="2027-12-31",
                build_start="2027-01-01", build_end="2027-12-31", origin="report")
    base.update(row)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_COLUMNS)
        writer.writeheader()
        writer.writerow(base)


def post_pdf(client, data, utility="DESC", name="r.pdf"):
    return client.post("/submissions/preview/pdf", data={"utility": utility}, files={"file": (name, data, "application/pdf")})


# ---- preview ----------------------------------------------------------------------------

def test_pdf_preview_marks_a_new_project(client):
    response = post_pdf(client, make_pdf(DESC_PAGE))
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "pdf" and body["rows"][0]["status"] == "new"
    assert body["rows"][0]["row"]["project_id"] == "DESC_6810O" and body["rows"][0]["errors"] == []


def test_pdf_preview_marks_an_update_with_its_changes(client, tmp_path):
    write_current(tmp_path / "projects_raw.csv", in_service_date="2026-06-30")
    entry = post_pdf(client, make_pdf(DESC_PAGE)).json()["rows"][0]
    assert entry["status"] == "update"
    assert entry["changes"]["in_service_date"] == ["2026-06-30", "2027-12-31"]


def test_pdf_preview_marks_an_identical_project_unchanged(client, tmp_path):
    write_current(tmp_path / "projects_raw.csv")
    entry = post_pdf(client, make_pdf(DESC_PAGE)).json()["rows"][0]
    assert entry["status"] == "unchanged"


@pytest.mark.parametrize("data,utility,status,fragment", [
    (b"just text", "DESC", 422, "not a PDF"),
    (b"%PDF-1.4 broken", "DESC", 422, "could not be opened"),
    (make_pdf(DESC_PAGE), "GPC", 422, "Dominion Energy SC PDF"),
    (make_pdf(DESC_PAGE), "XYZ", 422, "Choose"),
])
def test_bad_uploads_get_a_plain_message_not_a_500(client, data, utility, status, fragment):
    response = post_pdf(client, data, utility)
    assert response.status_code == status and fragment in response.json()["detail"]


def test_oversized_upload_is_413(client, monkeypatch):
    from pipeline import pdf_submission
    monkeypatch.setattr(pdf_submission, "MAX_BYTES", 50)
    monkeypatch.setattr(submissions, "MAX_BYTES", 50)
    assert post_pdf(client, make_pdf(DESC_PAGE)).status_code == 413


def test_form_preview_new_and_invalid(client):
    ok = client.post("/submissions/preview/form", json=FORM).json()
    assert ok["origin"] == "form" and ok["rows"][0]["status"] == "new" and ok["rows"][0]["row"]["project_id"] == "GPC_SUB1"
    bad = client.post("/submissions/preview/form", json={**FORM, "in_service_date": "13/45/2026"}).json()
    assert bad["rows"][0]["status"] == "invalid" and any("in_service_date" in e for e in bad["rows"][0]["errors"])
    assert client.post("/submissions/preview/form", json={**FORM, "utility": "XYZ"}).status_code == 422


# ---- commit -------------------------------------------------------------------------------

def commit_body(client, **over):
    row = client.post("/submissions/preview/form", json=FORM).json()["rows"][0]["row"]
    return {"utility": "GPC", "origin": "form", "submitted_by": "Ana", "rows": [row], **over}


def test_commit_saves_rows_starts_a_rebuild_and_labels_the_company(client):
    response = client.post("/submissions/commit", json=commit_body(client))
    assert response.status_code == 200
    body = response.json()
    assert len(body["saved"]) == 1 and body["job_id"] == "job-1" and body["skipped"] == []
    history = client.get("/submissions").json()
    assert history[0]["project_id"] == "GPC_SUB1" and history[0]["status"] == "active"
    assert history[0]["submitted_by"] == "Georgia Power (Ana)"
    assert client.get(f"/submissions/jobs/{body['job_id']}").json()["status"] == "done"


def test_commit_ignores_forged_status_and_ids(client):
    body = commit_body(client)
    body["rows"][0].update(status="rejected", submission_id="sub_evil", submitted_at="1999")
    client.post("/submissions/commit", json=body)
    saved = client.get("/submissions").json()[0]
    assert saved["status"] == "active" and saved["submission_id"] != "sub_evil"


def test_commit_revalidates_and_skips_bad_rows(client):
    body = commit_body(client)
    body["rows"].append({**body["rows"][0], "project_id": "GPC_2", "in_service_date": "not a date"})
    response = client.post("/submissions/commit", json=body)
    assert response.status_code == 200
    assert [s["project_id"] for s in response.json()["skipped"]] == ["GPC_2"]


def test_commit_rejects_duplicates_within_one_request_and_wrong_utility(client):
    body = commit_body(client)
    body["rows"].append(dict(body["rows"][0]))
    skipped = client.post("/submissions/commit", json=body).json()["skipped"]
    assert len(skipped) == 1 and "duplicate" in skipped[0]["reason"]
    wrong = commit_body(client, utility="DESC")
    response = client.post("/submissions/commit", json=wrong)
    assert response.status_code == 422 and "GPC" in response.json()["detail"]["skipped"][0]["reason"]


def test_commit_of_unchanged_or_empty_is_a_422_that_saves_nothing(client, tmp_path):
    write_current(tmp_path / "projects_raw.csv")
    row = post_pdf(client, make_pdf(DESC_PAGE)).json()["rows"][0]["row"]
    response = client.post("/submissions/commit", json={"utility": "DESC", "origin": "pdf", "submitted_by": "", "rows": [row]})
    assert response.status_code == 422 and response.json()["detail"]["skipped"][0]["reason"] == "unchanged"
    assert client.get("/submissions").json() == []
    assert submissions.rebuilder.requests == 0


def test_concurrent_commits_lose_nothing(client):
    results = []

    def go(n):
        own = TestClient(app)                              # one client per thread
        row = own.post("/submissions/preview/form", json={**FORM, "utility_project_id": f"C{n}"}).json()["rows"][0]["row"]
        results.append(own.post("/submissions/commit", json={"utility": "GPC", "origin": "form", "submitted_by": "", "rows": [row]}).status_code)

    threads = [threading.Thread(target=go, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == [200] * 6 and len(client.get("/submissions").json()) == 6


# ---- history, reject / restore, jobs -------------------------------------------------------

def test_reject_and_restore_are_reversible_and_start_rebuilds(client):
    client.post("/submissions/commit", json=commit_body(client))
    submission_id = client.get("/submissions").json()[0]["submission_id"]
    rejected = client.post(f"/submissions/{submission_id}/reject").json()
    assert rejected["status"] == "rejected" and rejected["job_id"]
    assert client.get("/submissions").json()[0]["status"] == "rejected"
    restored = client.post(f"/submissions/{submission_id}/restore").json()
    assert restored["status"] == "active"
    assert client.post("/submissions/sub_missing/reject").status_code == 404


def test_jobs_and_manual_rebuild(client):
    assert client.get("/submissions/jobs/unknown").status_code == 404
    job = client.post("/submissions/rebuild").json()["job_id"]
    assert client.get(f"/submissions/jobs/{job}").json() == {"status": "done", "message": ""}
