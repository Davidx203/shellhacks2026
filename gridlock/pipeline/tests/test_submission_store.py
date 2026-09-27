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


# ---- review fixes: validation hardening ------------------------------------------------

def good_row():
    return prepare_form(FORM)[0]


@pytest.mark.parametrize("field", ["project_name", "endpoint_a", "endpoint_b"])
@pytest.mark.parametrize("value", ["<img src=x onerror=alert(1)>", "Okatie > Bluffton", "a<b"])
def test_html_characters_are_rejected_in_names(field, value):
    row = {**good_row(), field: value}
    assert any("<" in e or ">" in e or "not allowed" in e for e in validate_submission(row)), validate_submission(row)


@pytest.mark.parametrize("field", ["project_name", "endpoint_a", "endpoint_b", "source_ref", "source_file"])
@pytest.mark.parametrize("prefix", ["=", "+", "@", "-", " =", "\t="])
def test_formula_prefixes_are_rejected_in_every_text_field(field, prefix):
    row = {**good_row(), field: prefix + "cmd|' /C calc'!A0"}
    assert validate_submission(row), (field, prefix)


def test_a_row_cannot_claim_another_utilitys_project_id():
    row = {**good_row(), "project_id": "DESC_6807B"}                     # utility is GPC
    assert any("project_id" in e for e in validate_submission(row))


def test_impossible_iso_dates_are_rejected_not_just_malformed_ones():
    for field in ("in_service_date", "build_start", "build_end", "start_date"):
        row = {**good_row(), field: "2026-13-45"}
        assert any(field in e for e in validate_submission(row)), field


def test_source_file_must_look_like_one_we_write():
    assert validate_submission({**good_row(), "source_file": "/etc/passwd"})
    assert validate_submission({**good_row(), "source_file": "submission:report.pdf#page3"}) == []


def test_every_real_report_row_still_passes_the_hardened_validation():
    rows = list(csv.DictReader(open(store.ROOT / "data" / "interim" / "projects_raw.csv", encoding="utf-8")))
    as_submitted = [{**r, "source_file": "form"} for r in rows]      # report rows carry report file paths
    bad = [(r["project_id"], validate_submission(r)) for r in as_submitted if validate_submission(r)]
    assert bad == []


# ---- review fixes: number grammar -------------------------------------------------------

@pytest.mark.parametrize("field,value,expected", [
    ("est_cost_usd", "$3,000,000", "3000000"),
    ("est_cost_usd", "3000000", "3000000"),
    ("est_cost_usd", " $ 12,500.4 ", "12500"),
    ("length_mi", "8.7 mi", "8.7"),
    ("length_mi", "12 miles", "12"),
    ("voltage_kv", "115 kV", "115"),
    ("voltage_kv", "230", "230"),
    ("voltage_kv", "230/115 kV", "230"),          # highest voltage mentioned, per the contract
    ("voltage_kv", "230-115KV", "230"),
])
def test_well_formed_numbers_are_normalised(field, value, expected):
    row, errors = prepare_form({**FORM, field: value})
    assert errors == [], errors
    assert row[field] == expected


@pytest.mark.parametrize("field,value", [
    ("est_cost_usd", "3e6"), ("est_cost_usd", "$3.5M"), ("est_cost_usd", "1,5"), ("est_cost_usd", "-500"),
    ("length_mi", "1,5"), ("length_mi", "about 5"), ("length_mi", "5-7"), ("length_mi", "1.2.3"),
    ("voltage_kv", "abc"), ("voltage_kv", "two thirty"), ("voltage_kv", "-115"),
])
def test_ambiguous_numbers_are_errors_not_silently_reinterpreted(field, value):
    row, errors = prepare_form({**FORM, field: value})
    assert any(field in e for e in errors), (field, value, errors)
    assert row[field] == ""


# ---- review fixes: atomic commit, reserved ids -------------------------------------------

def form_row(**over):
    row, errors = prepare_form({**FORM, **over})
    assert errors == [], errors
    return row


def test_commit_rows_skips_a_repeat_without_waiting_for_any_rebuild(tmp_path):
    path = tmp_path / "s.csv"
    baseline = [report()]
    change = {**clean_row(report(project_name="Hooks - Thurmond 115kV Tie: Rebuild")), "in_service_date": "2025-06-01"}
    ids, skipped = store.commit_rows([change], "pdf", "x", baseline, path=path)
    assert len(ids) == 1 and skipped == []
    ids, skipped = store.commit_rows([change], "pdf", "x", baseline, path=path)      # same body again, double click
    assert ids == [] and skipped == [{"project_id": "DESC_1", "reason": "unchanged"}]
    assert len(read_submissions(path)) == 1


def test_commit_rows_refuses_a_row_whose_status_changed_since_its_preview(tmp_path):
    path = tmp_path / "s.csv"
    first, second = form_row(project_name="First - Project 115kV: Rebuild"), form_row(project_name="Second - Project 115kV: Rebuild")
    assert first["project_id"] == second["project_id"] == "GPC_SUB1"                 # two previews before either commit
    ids, _ = store.commit_rows([first], "form", "a", [], expected={"GPC_SUB1": "new"}, path=path)
    assert len(ids) == 1
    ids, skipped = store.commit_rows([second], "form", "b", [], expected={"GPC_SUB1": "new"}, path=path)
    assert ids == [] and "changed since your preview" in skipped[0]["reason"]
    assert [r["project_name"] for r in read_submissions(path)] == ["First - Project 115kV: Rebuild"]


def test_reserved_ids_include_rejected_submissions_so_ids_are_never_reused(tmp_path):
    path = tmp_path / "s.csv"
    ids, _ = store.commit_rows([form_row()], "form", "a", [], path=path)
    set_status(ids[0], "rejected", path)
    assert "GPC_SUB1" in store.reserved_ids([], path)
    assert prepare_form(FORM, taken_ids=store.reserved_ids([], path))[0]["project_id"] == "GPC_SUB2"


def test_current_state_is_baseline_plus_active_submissions(tmp_path):
    path = tmp_path / "s.csv"
    ids, _ = store.commit_rows([{**clean_row(report()), "in_service_date": "2030-01-01"}], "pdf", "a", [report()], path=path)
    assert store.current_by_id([report()], path)["DESC_1"]["in_service_date"] == "2030-01-01"
    set_status(ids[0], "rejected", path)
    assert store.current_by_id([report()], path)["DESC_1"]["in_service_date"] == "2024-12-31"


def test_concurrent_identical_commits_save_exactly_one_revision(tmp_path):
    path = tmp_path / "s.csv"
    row = {**clean_row(report()), "in_service_date": "2031-01-01"}
    saved = []
    threads = [threading.Thread(target=lambda: saved.append(len(store.commit_rows([row], "pdf", "x", [report()], path=path)[0]))) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(saved) == [0] * 7 + [1] and len(read_submissions(path)) == 1


# ---- review fixes: updates change only what the submitter filled in --------------------------

def existing_project(**over):
    return report(project_id="GPC_20277", utility="GPC", state="GA", project_name="McIntosh - Purrysburg 230kV Rebuild",
                  endpoint_a="McIntosh", endpoint_b="Purrysburg", voltage_kv="230", est_cost_usd="1000000",
                  in_service_date="2026-06-01", build_start="2024-03-15", build_end="2026-06-01", project_type="rebuild",
                  given_lat_a="32.35", given_lon_a="-81.17", **over)


def update_payload(**over):
    return {"utility": "GPC", "utility_project_id": "20277", **over}


def test_updating_only_the_cost_changes_only_the_cost():
    current = {"GPC_20277": existing_project()}
    row, errors = prepare_form(update_payload(est_cost_usd="$4,000,000"), current_by_id=current)
    assert errors == []
    for field in ("project_name", "endpoint_a", "endpoint_b", "voltage_kv", "project_type", "in_service_date", "build_start", "build_end"):
        assert row[field] == "", field
    assert diff(row, current) == {"status": "update", "changes": {"est_cost_usd": ["1000000", "4000000"]}}
    merged = merge_rows([existing_project()], [{**dict.fromkeys(store.SUBMISSION_COLUMNS, ""), **row, "submission_id": "s", "submitted_at": "t", "status": "active", "origin": "form"}])[0]
    assert (merged["build_start"], merged["endpoint_a"], merged["given_lat_a"]) == ("2024-03-15", "McIntosh", "32.35")


def test_updating_the_in_service_date_keeps_the_real_build_start():
    current = {"GPC_20277": existing_project()}
    row, errors = prepare_form(update_payload(in_service_date="2027-01-31"), current_by_id=current)
    assert errors == [] and row["build_start"] == "" and (row["in_service_date"], row["build_end"]) == ("2027-01-31", "2027-01-31")


def test_an_update_that_would_put_the_start_after_the_end_is_rejected():
    current = {"GPC_20277": existing_project()}
    row, errors = prepare_form(update_payload(in_service_date="2023-06-01"), current_by_id=current)     # before the 2024-03-15 start
    assert any("build_start" in e for e in errors), errors


def test_a_new_name_on_an_update_reclassifies_but_does_not_rederive_endpoints():
    current = {"GPC_20277": existing_project()}
    row, errors = prepare_form(update_payload(project_name="McIntosh - Purrysburg 230kV RELAY MODERNIZATION"), current_by_id=current)
    assert errors == [] and row["project_type"] == "relay" and row["endpoint_a"] == "" and row["voltage_kv"] == ""


def test_a_project_id_that_does_not_exist_is_still_a_full_new_project():
    row, errors = prepare_form(update_payload(utility_project_id="99999"), current_by_id={"GPC_20277": existing_project()})
    assert any("project_name" in e or "in_service_date" in e for e in errors)     # new projects still need their required fields
