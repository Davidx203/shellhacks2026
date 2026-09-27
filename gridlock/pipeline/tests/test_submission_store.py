import csv
import threading

import pytest

from pipeline import submission_store as store
from pipeline.common import RAW_COLUMNS
from pipeline.submission_store import (
    append_submissions, clean_row, diff, history, merge_rows, prepare_form,
    read_submissions, set_status, validate_submission,
)

FORM = {
    "utility": "GPC", "project_name": "Okatie - Bluffton 115kV: Rebuild",
    "endpoint_a": "Okatie", "endpoint_b": "Bluffton", "voltage_kv": "115 kV",
    "length_mi": "8.7 mi", "est_cost_usd": "$3,000,000", "in_service_date": "06/01/2026",
}


def report(**over):
    row = dict.fromkeys(RAW_COLUMNS, "")
    row.update(project_id="DESC_1", utility="DESC", state="SC", project_name="Hooks - Thurmond 115kV Tie: Rebuild",
               endpoint_a="Hooks", endpoint_b="Thurmond", voltage_kv="115", project_type="rebuild",
               in_service_date="2024-12-31", build_start="2024-01-01", build_end="2024-12-31")
    row.update(over)
    return row


# ---- prepare_form -----------------------------------------------------------

def test_form_values_are_normalised_to_the_contract():
    row, errors = prepare_form(FORM)
    assert errors == []
    assert row["project_id"] == "GPC_SUB1" and row["state"] == "GA" and row["utility"] == "GPC"
    assert row["voltage_kv"] == "115" and row["est_cost_usd"] == "3000000" and row["length_mi"] == "8.7"
    assert row["in_service_date"] == "2026-06-01"
    assert (row["build_start"], row["build_end"]) == ("2026-01-01", "2026-06-01")
    assert row["project_type"] == "rebuild" and row["source_file"] == "form"


def test_lowercase_utility_and_stray_whitespace_are_accepted():
    row, errors = prepare_form({**FORM, "utility": " gpc ", "project_name": "  Okatie -\n Bluffton   115kV  Rebuild "})
    assert errors == [] and row["utility"] == "GPC" and "\n" not in row["project_name"]
    assert "  " not in row["project_name"]


def test_endpoints_and_voltage_are_derived_from_the_name_when_left_blank():
    row, errors = prepare_form({"utility": "DESC", "project_name": "Okatie-Bluffton 115kV: Rebuild", "in_service_date": "2026-06-01"})
    assert errors == [] and (row["endpoint_a"], row["endpoint_b"], row["voltage_kv"]) == ("Okatie", "Bluffton", "115")


@pytest.mark.parametrize("field,value,fragment", [
    ("voltage_kv", "abc", "voltage_kv"),
    ("est_cost_usd", "1.2.3", "est_cost_usd"),
    ("in_service_date", "13/45/2026", "in_service_date"),
    ("in_service_date", "next spring", "in_service_date"),
    ("build_start", "2027-01-01", "build_start"),
    ("project_name", "", "project_name"),
    ("in_service_date", "", "in_service_date"),
    ("utility_project_id", "bad id/with slash", "utility_project_id"),
    ("project_name", "=HYPERLINK(\"http://x\")", "must not start"),
])
def test_bad_form_values_are_reported_by_field(field, value, fragment):
    payload = {**FORM, field: value}
    row, errors = prepare_form(payload)
    assert any(fragment in e for e in errors), errors


def test_invalid_utility_returns_no_row():
    row, errors = prepare_form({**FORM, "utility": "XYZ"})
    assert row == {} and errors


def test_user_ids_get_the_prefix_and_generated_ids_skip_taken_ones():
    assert prepare_form({**FORM, "utility_project_id": "20 277"})[0]["project_id"] == "GPC_20277"
    assert prepare_form({**FORM, "utility_project_id": "GPC_20277"})[0]["project_id"] == "GPC_20277"
    assert prepare_form(FORM, taken_ids={"GPC_SUB1", "GPC_SUB2"})[0]["project_id"] == "GPC_SUB3"


@pytest.mark.parametrize("coords,fragment", [
    ({"lat_a": "-81.1", "lon_a": "32.3"}, "outside Georgia and South Carolina"),
    ({"lat_a": "40.0", "lon_a": "-81.1"}, "outside Georgia and South Carolina"),
    ({"lat_a": "32.3"}, "both latitude and longitude"),
    ({"lat_b": "32.3", "lon_b": "-81.1", "endpoint_b": ""}, "without a name"),
])
def test_bad_coordinates_are_rejected(coords, fragment):
    row, errors = prepare_form({**FORM, **coords})
    assert any(fragment in e for e in errors), errors


def test_good_coordinates_are_kept_as_given_coordinates():
    row, errors = prepare_form({**FORM, "lat_a": "32.2776", "lon_a": "-80.9686"})
    assert errors == [] and (row["given_lat_a"], row["given_lon_a"]) == ("32.2776", "-80.9686")


def test_validate_submission_rejects_forged_or_unsafe_rows():
    row, _ = prepare_form(FORM)
    assert validate_submission(row) == []
    assert validate_submission({**row, "project_id": "GPC_../x"})
    assert validate_submission({**row, "project_name": "x" * 201})
    assert validate_submission({**row, "endpoint_a": ""})


def test_clean_row_keeps_only_row_keys_as_strings():
    row, _ = prepare_form(FORM)
    forged = {**row, "status": "rejected", "submission_id": "sub_evil", "voltage_kv": 115}
    cleaned = clean_row(forged)
    assert "status" not in cleaned and "submission_id" not in cleaned and cleaned["voltage_kv"] == "115"


# ---- diff ---------------------------------------------------------------------

def test_diff_new_update_unchanged_and_numeric_equality():
    current = {"DESC_1": report(length_mi="18.0", in_service_date="2024-12-31")}
    assert diff({"project_id": "DESC_9", "project_name": "x"}, current)["status"] == "new"
    update = diff({"project_id": "DESC_1", "in_service_date": "2025-06-01"}, current)
    assert update == {"status": "update", "changes": {"in_service_date": ["2024-12-31", "2025-06-01"]}}
    assert diff({"project_id": "DESC_1", "length_mi": "18", "in_service_date": "2024-12-31"}, current)["status"] == "unchanged"
    assert diff({"project_id": "DESC_1", "in_service_date": ""}, current)["status"] == "unchanged"


# ---- merge --------------------------------------------------------------------

def sub(**over):
    row = dict.fromkeys(store.SUBMISSION_COLUMNS, "")
    row.update(project_id="DESC_1", utility="DESC", state="SC", origin="form", submission_id="sub_1",
               submitted_at="2026-09-27T10:00:00.000000Z", status="active", submitted_by="Dominion Energy SC")
    row.update(over)
    return row


def test_merge_override_blank_keeps_existing_and_new_ids_are_appended():
    merged = merge_rows([report()], [sub(in_service_date="2025-06-01", project_name=""), sub(project_id="DESC_SUB1", project_name="New line - X 115kV", submission_id="sub_2")])
    by_id = {r["project_id"]: r for r in merged}
    assert by_id["DESC_1"]["in_service_date"] == "2025-06-01"
    assert by_id["DESC_1"]["project_name"] == "Hooks - Thurmond 115kV Tie: Rebuild"
    assert by_id["DESC_1"]["origin"] == "form" and by_id["DESC_1"]["submission_id"] == "sub_1"
    assert "DESC_SUB1" in by_id and len(merged) == 2
    assert all(set(r) == set(RAW_COLUMNS) for r in merged)


def test_report_rows_get_origin_report():
    assert merge_rows([report()], [])[0]["origin"] == "report"


def test_latest_active_submission_wins_and_rejected_ones_are_ignored():
    early = sub(in_service_date="2025-01-01", submission_id="sub_a", submitted_at="2026-09-27T09:00:00.000000Z")
    late = sub(in_service_date="2026-01-01", submission_id="sub_b", submitted_at="2026-09-27T10:00:00.000000Z")
    assert merge_rows([report()], [early, late])[0]["in_service_date"] == "2026-01-01"
    rejected = {**late, "status": "rejected"}
    assert merge_rows([report()], [early, rejected])[0]["in_service_date"] == "2025-01-01"
    assert merge_rows([report()], [{**early, "status": "rejected"}, rejected])[0]["in_service_date"] == "2024-12-31"


def test_relay_rule_is_reapplied_after_a_merge():
    merged = merge_rows([report()], [sub(project_name="Hooks RELAY MODERNIZATION")])
    assert merged[0]["project_type"] == "relay" and merged[0]["endpoint_b"] == ""


# ---- storage ------------------------------------------------------------------

def test_append_read_status_and_history(tmp_path):
    path = tmp_path / "submissions.csv"
    assert read_submissions(path) == []
    row, _ = prepare_form(FORM)
    ids = append_submissions([row], "form", "Georgia Power (Ana)", path)
    assert len(ids) == 1 and ids[0].startswith("sub_")
    saved = read_submissions(path)[0]
    assert saved["status"] == "active" and saved["origin"] == "form" and saved["submitted_by"] == "Georgia Power (Ana)"
    assert saved["submitted_at"].endswith("Z") and saved["project_id"] == "GPC_SUB1"
    set_status(ids[0], "rejected", path)
    assert read_submissions(path)[0]["status"] == "rejected"
    set_status(ids[0], "active", path)
    assert history(path)[0]["submission_id"] == ids[0]
    with pytest.raises(KeyError):
        set_status("sub_missing", "rejected", path)


def test_history_is_newest_first(tmp_path):
    path = tmp_path / "s.csv"
    first = append_submissions([prepare_form(FORM)[0]], "form", "a", path)[0]
    second = append_submissions([prepare_form({**FORM, "utility_project_id": "2"})[0]], "form", "a", path)[0]
    assert [h["submission_id"] for h in history(path)] == [second, first]


def test_concurrent_appends_lose_nothing_and_leave_no_temp_files(tmp_path):
    path = tmp_path / "s.csv"
    errors = []

    def worker(n):
        try:
            for i in range(5):
                row, _ = prepare_form({**FORM, "utility_project_id": f"{n}-{i}"})
                append_submissions([row], "form", f"t{n}", path)
        except Exception as error:  # pragma: no cover - the assertion below reports it
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    rows = read_submissions(path)
    assert len(rows) == 40 and len({r["submission_id"] for r in rows}) == 40
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".tmp") == []
    with path.open(newline="", encoding="utf-8") as f:
        assert csv.DictReader(f).fieldnames == store.SUBMISSION_COLUMNS
