"""
Structured table extraction from PDFs.

PyPDF2 (used by document_processing) flattens a PDF to a stream of text, which
mangles tables — columns run together and row structure is lost, so a question
like "what was the score in row 12?" can't be answered. This module pulls tables
out *as tables* and emits each row as a labelled "Col: val | Col: val" line — the
same shape `_extract_excel_blocks` produces for spreadsheets, which the retrieval
pipeline and the exact-match lookup already handle well.

Two engines, chosen by `config.table_engine()`:

- **pdfplumber** (default): pure-Python, no torch, runs on Python 3.9 and the
  8 GB / no-GPU laptop. This is the Lite-safe path.
- **docling** (opt-in, Power mode): IBM's layout-aware parser with the TableFormer
  model — higher quality on complex/borderless tables, but needs Python ≥3.10 and
  pulls in torch, so it is NOT installed by default and is only used when the user
  is on Power mode AND it's actually importable.

Everything is defensive: a missing engine (or a parse error) degrades to the next
option and finally to "no tables", so uploads of normal PDFs never break. When
neither engine is available this module is a no-op and document_processing keeps
its existing PyPDF2 behavior exactly.
"""

from __future__ import annotations

import logging
import sys
from typing import List, Tuple

import config

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Optional engines — imported defensively (mirrors the OCR import pattern in
# document_processing.py). Their absence must never break a normal upload.
# ─────────────────────────────────────────────────────────────────────
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    pdfplumber = None
    PDFPLUMBER_AVAILABLE = False

# Docling needs Python ≥3.10; don't even attempt the import on 3.9 (it would
# error noisily). The heavy `docling` import itself is deferred to call time so
# importing this module stays cheap on the Lite path.
DOCLING_PYTHON_OK = sys.version_info >= (3, 10)


def _docling_importable() -> bool:
    """Whether docling can actually be imported (Python ≥3.10 + installed)."""
    if not DOCLING_PYTHON_OK:
        return False
    try:
        import docling  # noqa: F401
        return True
    except Exception:
        return False


def tables_available() -> bool:
    """True when at least one table engine can run (so callers can skip work)."""
    return PDFPLUMBER_AVAILABLE or _docling_importable()


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────
def extract_pdf_tables(file_path: str) -> List[Tuple[str, dict]]:
    """
    Extract tables from a PDF as (text, metadata) chunks.

    Each returned chunk is one table's rows rendered as labelled lines, with
    metadata `{"page": n, "table": i, "content_type": "table"}` so citations can
    point at it. Resolves the configured engine to one that's actually installed,
    falling back pdfplumber → (docling) → []. Never raises.
    """
    engine = config.table_engine()
    if engine == "off":
        return []

    # Resolve to an engine that's truly available.
    if engine == "docling" and _docling_importable():
        out = _extract_with_docling(file_path)
        if out:
            return out
        # docling found nothing or failed → try the lighter path before giving up
    if PDFPLUMBER_AVAILABLE:
        return _extract_with_pdfplumber(file_path)
    if engine != "docling" and _docling_importable():
        return _extract_with_docling(file_path)
    return []


# ─────────────────────────────────────────────────────────────────────
# pdfplumber engine (Lite-safe default)
# ─────────────────────────────────────────────────────────────────────
def _rows_to_text(rows: List[List]) -> str:
    """
    Render a raw table (list of rows, each a list of cell strings) as labelled
    lines using the first non-empty row as the header:

        Name: Alice | Score: 91 | City: Chennai
        Name: Bob   | Score: 88 | City: Madurai

    Falls back to plain " | "-joined cells when there's no usable header.
    """
    cleaned = [[("" if c is None else str(c).strip()) for c in row] for row in rows]
    cleaned = [r for r in cleaned if any(cell for cell in r)]
    if not cleaned:
        return ""

    header = cleaned[0]
    has_header = any(h for h in header)
    body = cleaned[1:] if has_header else cleaned

    lines: List[str] = []
    for row in body:
        if has_header:
            parts = [
                f"{header[i]}: {val}" if i < len(header) and header[i] else val
                for i, val in enumerate(row)
                if val
            ]
        else:
            parts = [val for val in row if val]
        if parts:
            lines.append(" | ".join(parts))
    return "\n".join(lines)


def _extract_with_pdfplumber(file_path: str) -> List[Tuple[str, dict]]:
    """Per-page table extraction with pdfplumber → labelled-row chunks."""
    chunks: List[Tuple[str, dict]] = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):
                try:
                    tables = page.extract_tables() or []
                except Exception as e:
                    logger.warning(f"pdfplumber page {page_no} failed: {e}")
                    continue
                for t_idx, raw in enumerate(tables, start=1):
                    text = _rows_to_text(raw)
                    if text.strip():
                        chunks.append(
                            (text, {"page": page_no, "table": t_idx,
                                    "content_type": "table"})
                        )
    except Exception as e:
        logger.warning(f"pdfplumber could not open {file_path}: {e}")
    return chunks


# ─────────────────────────────────────────────────────────────────────
# docling engine (optional, Power mode, Python ≥3.10)
# ─────────────────────────────────────────────────────────────────────
def _extract_with_docling(file_path: str) -> List[Tuple[str, dict]]:
    """
    High-quality table extraction with docling's TableFormer. Imported lazily so
    the heavy dependency only loads when actually used. Each detected table is
    exported to markdown and tagged with its page when docling provides one.
    """
    try:
        from docling.document_converter import DocumentConverter
    except Exception as e:
        logger.info(f"docling unavailable: {e}")
        return []

    chunks: List[Tuple[str, dict]] = []
    try:
        result = DocumentConverter().convert(file_path)
        doc = result.document
        for t_idx, table in enumerate(getattr(doc, "tables", []) or [], start=1):
            try:
                text = table.export_to_markdown()
            except Exception:
                text = str(getattr(table, "text", "") or "")
            if not text.strip():
                continue
            # Best-effort page number from docling's provenance, if present.
            page = None
            prov = getattr(table, "prov", None)
            if prov:
                page = getattr(prov[0], "page_no", None) or getattr(prov[0], "page", None)
            meta = {"table": t_idx, "content_type": "table"}
            if page:
                meta["page"] = page
            chunks.append((text, meta))
    except Exception as e:
        logger.warning(f"docling parse failed for {file_path}: {e}")
    return chunks
