import re
from pathlib import Path

import pytest

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
GPC = RAW / "gpc_irp_vol3.txt"
PAGES = RAW / "desc_pages"

needs_raw = pytest.mark.skipif(not GPC.exists(), reason="run pipeline/extract_pdfs.py first")


@needs_raw
def test_gpc_has_208_detail_blocks():
    n = len(re.findall(r"^Teams # ", GPC.read_text(encoding="utf-8"), re.M))
    assert n == 208, n


@needs_raw
def test_desc_has_44_pages_with_required_labels():
    files = sorted(PAGES.glob("*.txt"))
    assert len(files) == 44
    for f in files:
        t = f.read_text(encoding="utf-8")
        for label in ("Project ID", "Planned In-Service Date", "Estimated Project Cost"):
            assert label in t, (f.name, label)
