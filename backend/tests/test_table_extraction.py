"""
Tests for structured PDF table extraction (Feature 2).

These stay deterministic and Python-3.9-safe: the row-rendering logic is tested
directly (no PDF needed), engine selection + graceful degradation are tested via
settings, and a real pdfplumber round-trip is gated on `reportlab` being present
to generate a table PDF (skipped where it isn't, e.g. the 3.9 CI box).
"""

import sys

import pytest

import config
from services import table_extraction as te


# ── Row rendering (pure logic, no PDF) ───────────────────────────────

def test_rows_to_text_uses_header_labels():
    rows = [["Name", "Score", "City"],
            ["Alice", "91", "Chennai"],
            ["Bob", "88", "Madurai"]]
    out = te._rows_to_text(rows)
    assert "Name: Alice | Score: 91 | City: Chennai" in out
    assert "Name: Bob | Score: 88 | City: Madurai" in out


def test_rows_to_text_skips_empty_cells_and_rows():
    rows = [["Name", "Score"],
            ["Alice", ""],          # empty cell dropped
            ["", ""],               # whole row dropped
            [None, "5"]]            # None coerced
    out = te._rows_to_text(rows)
    assert "Name: Alice" in out
    assert "Score: 5" in out
    assert out.count("\n") == 1     # only two non-empty body rows


def test_rows_to_text_empty_returns_blank():
    assert te._rows_to_text([]) == ""
    assert te._rows_to_text([[None, ""], ["", None]]) == ""


# ── Engine selection + graceful degradation ──────────────────────────

def test_extract_off_returns_empty(restore_settings, tmp_path):
    config.save_settings({"table_engine": "off"})
    fake = tmp_path / "x.pdf"
    fake.write_bytes(b"%PDF-1.4")          # not a real table; engine is off anyway
    assert te.extract_pdf_tables(str(fake)) == []


def test_extract_never_raises_on_garbage(restore_settings, tmp_path):
    # A non-PDF file must degrade to [] (defensive), never raise.
    config.save_settings({"table_engine": "pdfplumber"})
    junk = tmp_path / "junk.pdf"
    junk.write_text("this is not a pdf", encoding="utf-8")
    assert te.extract_pdf_tables(str(junk)) == []


def test_docling_skipped_on_py39():
    # Docling needs Python >=3.10; on older interpreters it must report False
    # (never attempt the import) so the Lite/3.9 path is untouched.
    if sys.version_info < (3, 10):
        assert te.DOCLING_PYTHON_OK is False
        assert te._docling_importable() is False


def test_tables_available_is_bool():
    assert isinstance(te.tables_available(), bool)


# ── Real round-trip (only where we can synthesize a table PDF) ───────

def test_pdfplumber_extracts_real_table(restore_settings, tmp_path):
    reportlab = pytest.importorskip("reportlab")  # skip if we can't build a PDF
    if not te.PDFPLUMBER_AVAILABLE:
        pytest.skip("pdfplumber not installed")
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
    from reportlab.lib import colors

    pdf_path = tmp_path / "table.pdf"
    data = [["Name", "Score", "City"],
            ["Alice", "91", "Chennai"],
            ["Bob", "88", "Madurai"]]
    doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
    table = Table(data)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    doc.build([table])

    config.save_settings({"table_engine": "pdfplumber"})
    chunks = te.extract_pdf_tables(str(pdf_path))
    assert chunks, "expected at least one table chunk"
    text, meta = chunks[0]
    assert meta.get("content_type") == "table"
    assert meta.get("page") == 1
    assert "Alice" in text and "Chennai" in text
