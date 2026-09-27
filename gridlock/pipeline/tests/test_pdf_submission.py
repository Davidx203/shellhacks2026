from pathlib import Path

import pymupdf
import pytest

from pipeline import pdf_submission
from pipeline.pdf_submission import FileTooLarge, SubmissionError, read_pdf, safe_name

DESC_PAGE = """Project 43 of 44
Dominion Energy South Carolina
Planned Transmission Projects $2M and above Total
5 Year Budget
Urquhart - Aiken PSA 46 kV: Rebuild
Project ID
6810 O
Project Description
Rebuilding the section of 46 kV line from Urquhart to the Aiken PSA tap point. 4.5 miles.
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

GPC_BLOCK = """Page 44 of 304
THALMANN AND COLERAIN 23O KV LINE RELAY PANEL UPGRADES
Teams # 21046
Need Date 06/01/2025 Start Date 12/01/2024
Description
"""

REPO = Path(__file__).resolve().parents[3]
REAL_DESC = REPO / "Sperry-Tech-Challenge" / "Project Listings" / "Dominion Energy" / "2024-2028-2million-and-above-project-descriptions.pdf"
REAL_GPC = REPO / "Sperry-Tech-Challenge" / "Project Listings" / "Georgia Power" / "2025 IRP Volume 3 PUBLIC DISCLOSURE.pdf"


def make_pdf(pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((36, 40), text, fontsize=7)
    data = doc.tobytes()
    doc.close()
    return data


def test_dominion_page_becomes_a_contract_row():
    rows = read_pdf(make_pdf([DESC_PAGE]), "DESC", "report.pdf")
    assert len(rows) == 1
    row = rows[0]
    assert row["project_id"] == "DESC_6810O" and row["utility"] == "DESC" and row["state"] == "SC"
    assert row["project_type"] == "rebuild"
    assert row["in_service_date"] == "2027-12-31" and row["est_cost_usd"] == 3000000
    assert row["source_file"] == "submission:report.pdf#page1"


def test_georgia_power_block_becomes_a_contract_row():
    rows = read_pdf(make_pdf([GPC_BLOCK]), "GPC", "irp.pdf")
    assert [r["project_id"] for r in rows] == ["GPC_21046"]
    assert rows[0]["project_type"] == "relay" and rows[0]["endpoint_b"] == ""
    assert rows[0]["voltage_kv"] == 230 and rows[0]["source_file"] == "submission:irp.pdf"


def test_wrong_company_selected_is_explained():
    with pytest.raises(SubmissionError, match="Dominion Energy SC PDF but you selected Georgia Power"):
        read_pdf(make_pdf([DESC_PAGE]), "GPC")


def test_not_a_pdf():
    with pytest.raises(SubmissionError, match="not a PDF"):
        read_pdf(b"hello world", "GPC")


def test_corrupt_pdf():
    with pytest.raises(SubmissionError, match="could not be opened"):
        read_pdf(b"%PDF-1.4 this is not really a pdf", "GPC")


def test_scanned_pdf_without_text():
    with pytest.raises(SubmissionError, match="no text"):
        read_pdf(make_pdf(["", ""]), "GPC")


def test_unrecognised_layout():
    with pytest.raises(SubmissionError, match="layout is not recognised"):
        read_pdf(make_pdf(["Quarterly newsletter\nNothing about projects here"]), "GPC")


def test_truncated_dominion_page_names_the_page():
    with pytest.raises(SubmissionError, match="Page 1"):
        read_pdf(make_pdf(["Project ID\nPlanned In-Service Date\n12/31/2027"]), "DESC")


def test_mixed_layouts_are_rejected():
    with pytest.raises(SubmissionError, match="mixes"):
        read_pdf(make_pdf([DESC_PAGE, GPC_BLOCK]), "DESC")


def test_oversized_upload(monkeypatch):
    monkeypatch.setattr(pdf_submission, "MAX_BYTES", 100)
    with pytest.raises(FileTooLarge, match="20 MB"):
        read_pdf(b"%PDF" + b"0" * 200, "GPC")


def test_too_many_pages(monkeypatch):
    monkeypatch.setattr(pdf_submission, "MAX_PAGES", 1)
    with pytest.raises(SubmissionError, match="limit is 1"):
        read_pdf(make_pdf([DESC_PAGE, DESC_PAGE]), "DESC")


def test_safe_name_strips_paths_and_odd_characters():
    assert safe_name("../../etc/passwd.pdf") == "passwd.pdf"
    assert safe_name("C:\\temp\\rép ort<>.pdf") == "rép ort__.pdf"
    assert safe_name("") == "upload.pdf"
    assert len(safe_name("x" * 500 + ".pdf")) == 100


@pytest.mark.skipif(not REAL_DESC.exists(), reason="source PDF not in the repo")
def test_real_dominion_report_gives_44_rows():
    rows = read_pdf(REAL_DESC.read_bytes(), "DESC", REAL_DESC.name)
    assert len(rows) == 44 and len({r["project_id"] for r in rows}) == 44


@pytest.mark.skipif(not REAL_GPC.exists(), reason="source PDF not in the repo")
def test_real_georgia_power_report_gives_208_rows():
    rows = read_pdf(REAL_GPC.read_bytes(), "GPC", REAL_GPC.name)
    assert len(rows) == 208
