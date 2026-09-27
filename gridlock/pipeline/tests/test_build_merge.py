import csv

from pipeline import build_raw
from pipeline.common import COLUMNS, RAW_COLUMNS
from pipeline.submission_store import SUBMISSION_COLUMNS


def write_csv(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def baseline_row(**over):
    row = dict.fromkeys(COLUMNS, "")
    row.update(project_id="DESC_1", utility="DESC", state="SC", project_name="Hooks - Thurmond 115kV Tie: Rebuild",
               endpoint_a="Hooks", endpoint_b="Thurmond", voltage_kv="115", project_type="rebuild",
               in_service_date="2024-12-31", build_start="2024-01-01", build_end="2024-12-31")
    row.update(over)
    return row


def submission_row(**over):
    row = dict.fromkeys(SUBMISSION_COLUMNS, "")
    row.update(project_id="DESC_1", utility="DESC", state="SC", origin="pdf", submission_id="sub_1",
               submitted_at="2026-09-27T10:00:00.000000Z", status="active", in_service_date="2025-06-01")
    row.update(over)
    return row


def test_build_uses_the_baseline_when_report_text_is_missing_and_merges_submissions(tmp_path):
    baseline = tmp_path / "projects_report.csv"
    submissions = tmp_path / "submissions.csv"
    write_csv(baseline, COLUMNS, [baseline_row()])
    write_csv(submissions, SUBMISSION_COLUMNS, [submission_row(), submission_row(project_id="DESC_SUB1", project_name="New - Line 115kV", submission_id="sub_2", state="SC")])
    rows = build_raw.build(raw=tmp_path / "no-report-text", baseline=baseline, submissions=submissions)
    by_id = {r["project_id"]: r for r in rows}
    assert by_id["DESC_1"]["in_service_date"] == "2025-06-01" and by_id["DESC_1"]["origin"] == "pdf"
    assert by_id["DESC_1"]["project_name"].startswith("Hooks")
    assert by_id["DESC_SUB1"]["origin"] == "pdf" and len(rows) == 2


def test_write_uses_the_extended_columns(tmp_path):
    baseline = tmp_path / "b.csv"
    write_csv(baseline, COLUMNS, [baseline_row()])
    rows = build_raw.build(raw=tmp_path / "none", baseline=baseline, submissions=tmp_path / "none.csv")
    out = tmp_path / "raw.csv"
    build_raw.write(rows, out)
    with out.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)
    assert reader.fieldnames == RAW_COLUMNS and data[0]["origin"] == "report"


def test_missing_baseline_and_report_text_is_a_clear_error(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError, match="projects_report.csv"):
        build_raw.build(raw=tmp_path / "none", baseline=tmp_path / "projects_report.csv", submissions=tmp_path / "none.csv")


# ---- review fixes: files a rebuild rewrites are replaced atomically ---------------------------

def test_a_failed_write_leaves_the_previous_file_untouched_and_no_temp_files(tmp_path):
    import pytest
    out = tmp_path / "projects_raw.csv"
    build_raw.write([dict(baseline_row(), origin="report")], out)
    before = out.read_text(encoding="utf-8")
    with pytest.raises(AttributeError):
        build_raw.write([dict(baseline_row(project_id="DESC_2"), origin="report"), object()], out)   # blows up mid-write
    assert out.read_text(encoding="utf-8") == before
    assert [p.name for p in tmp_path.iterdir()] == ["projects_raw.csv"]
