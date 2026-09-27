"""Read a submitted PDF in one of our two report layouts into contract rows."""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from .classify import finalize_row
from .parse_desc import parse_page
from .parse_gpc import parse_text

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 800
UTILITY_NAMES = {"GPC": "Georgia Power", "DESC": "Dominion Energy SC"}


class SubmissionError(ValueError):
    """A problem with the upload that the submitter can act on; str(error) is safe to show."""


class FileTooLarge(SubmissionError):
    """The upload exceeds MAX_BYTES."""


def safe_name(filename):
    name = Path(str(filename or "upload.pdf").replace("\\", "/")).name
    name = re.sub(r"[^\w. \-]", "_", name).strip()
    return name[:100] or "upload.pdf"


def _is_dominion_page(text):
    return "Project ID" in text and "Planned In-Service Date" in text


def read_pdf(data, utility, filename="upload.pdf"):
    if len(data) > MAX_BYTES:
        raise FileTooLarge("The PDF is larger than 20 MB.")
    if not data.startswith(b"%PDF"):
        raise SubmissionError("This file is not a PDF.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as error:
        raise SubmissionError("The PDF could not be opened; it may be damaged.") from error
    with doc:
        if doc.page_count > MAX_PAGES:
            raise SubmissionError(f"The PDF has {doc.page_count} pages; the limit is {MAX_PAGES}.")
        pages = [page.get_text() for page in doc]
    if not "".join(pages).strip():
        raise SubmissionError("The PDF has no text (it looks scanned). Use the manual form instead.")

    source = f"submission:{safe_name(filename)}"
    text = "\n".join(pages)
    try:
        gpc_rows = parse_text(text, source) if re.search(r"^Teams # ", text, re.M) else []
    except (IndexError, ValueError) as error:
        raise SubmissionError("A Georgia Power project block could not be read.") from error
    desc_rows = []
    for number, page_text in enumerate(pages, 1):
        if not _is_dominion_page(page_text):
            continue
        try:
            desc_rows.append(parse_page(page_text, f"{source}#page{number}"))
        except (StopIteration, ValueError, IndexError) as error:
            raise SubmissionError(f"Page {number} looks like a Dominion project page but could not be read.") from error

    if gpc_rows and desc_rows:
        raise SubmissionError("This PDF mixes Georgia Power and Dominion layouts; upload them separately.")
    if not gpc_rows and not desc_rows:
        raise SubmissionError(
            "No projects found: the layout is not recognised. Upload a Georgia Power IRP or a Dominion "
            "project description PDF, or use the manual form."
        )
    detected = "GPC" if gpc_rows else "DESC"
    if detected != utility:
        raise SubmissionError(
            f"This looks like a {UTILITY_NAMES[detected]} PDF but you selected {UTILITY_NAMES[utility]}."
        )
    return [finalize_row(row) for row in (gpc_rows or desc_rows)]
