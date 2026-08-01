"""Lightweight PDF generation — English/Latin-1 text only (see Phase 4 plan).

Hebrew/RTL isn't supported yet: fpdf2's core fonts (Helvetica etc.) can only
encode Latin-1 characters. Adding real Unicode/RTL support means bundling a
TTF font plus `python-bidi` reordering — deliberately deferred.
"""
from __future__ import annotations

import re
import uuid

from fpdf import FPDF
from fpdf.errors import FPDFUnicodeEncodingException

from utils.paths import app_dir

GENERATED_DIR = app_dir() / "generated"


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    return slug or "document"


def generate_pdf(title: str, content: str) -> tuple[str, str]:
    """Render title + content to a PDF. Returns (file_id, filename).

    Raises ValueError with a user-facing message if the text can't be
    encoded in the core font's Latin-1 charset (e.g. Hebrew).
    """
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.multi_cell(0, 10, title)
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 11)
        for paragraph in content.split("\n\n"):
            pdf.multi_cell(0, 7, paragraph.strip())
            pdf.ln(3)
        pdf_bytes = bytes(pdf.output())
    except FPDFUnicodeEncodingException:
        raise ValueError(
            "PDF export currently only supports English/Latin-script text — "
            "the requested content contains characters (e.g. Hebrew) that "
            "can't be rendered yet."
        )

    file_id = str(uuid.uuid4())
    filename = f"{_slugify(title)}.pdf"
    out_dir = GENERATED_DIR / file_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / filename).write_bytes(pdf_bytes)

    return file_id, filename
