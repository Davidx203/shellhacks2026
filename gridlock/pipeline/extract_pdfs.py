"""Extract text from the two source PDFs into data/raw/."""
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT.parent / "Sperry-Tech-Challenge" / "Project Listings"
GPC_PDF = SRC / "Georgia Power" / "2025 IRP Volume 3 PUBLIC DISCLOSURE.pdf"
DESC_PDF = SRC / "Dominion Energy" / "2024-2028-2million-and-above-project-descriptions.pdf"
RAW = ROOT / "data" / "raw"


def extract_gpc(pdf=GPC_PDF, out=RAW / "gpc_irp_vol3.txt"):
    with pymupdf.open(pdf) as doc:
        out.write_text("\n".join(page.get_text() for page in doc), encoding="utf-8")


def extract_desc(pdf=DESC_PDF, out_dir=RAW / "desc_pages"):
    out_dir.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc, 1):
            (out_dir / f"{i}.txt").write_text(page.get_text(), encoding="utf-8")


if __name__ == "__main__":
    extract_gpc()
    extract_desc()
