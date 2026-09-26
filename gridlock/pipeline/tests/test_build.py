from pathlib import Path

import pytest

from pipeline.build_raw import build

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


@pytest.mark.skipif(not (RAW / "gpc_irp_vol3.txt").exists(), reason="run extract_pdfs.py first")
def test_build_combines_both_utilities():
    rows = build()
    assert len(rows) == 252
    assert sum(r["utility"] == "GPC" for r in rows) == 208
    assert sum(r["utility"] == "DESC" for r in rows) == 44
    assert all(r["endpoint_b"] == "" for r in rows if r["project_type"] == "relay")
    assert sum(r["project_type"] == "other" for r in rows) / len(rows) < 0.30  # leftovers are unlabeled "A - B kV LINE" names
