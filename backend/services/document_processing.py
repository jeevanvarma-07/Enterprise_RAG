import os
from typing import List, Tuple

import PyPDF2
import pandas as pd
from PIL import Image
from langchain.text_splitter import RecursiveCharacterTextSplitter

import config

# ─────────────────────────────────────────────────────────────────────
# Optional OCR stack. Both pytesseract (+ the Tesseract binary) and pdf2image
# (+ Poppler) are heavy, OS-level dependencies that the Lite profile does NOT
# require. Import them defensively so the app — and crucially, *uploads* of
# normal text PDFs / spreadsheets / txt — keep working even when OCR isn't
# installed. OCR is also gated at runtime by config.ocr_enabled() (off on Lite).
# ─────────────────────────────────────────────────────────────────────
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    pytesseract = None
    TESSERACT_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False


def _ocr_ready() -> bool:
    """True only when OCR is both installed and enabled by the active profile."""
    return TESSERACT_AVAILABLE and config.ocr_enabled()


def process_document(file_path: str) -> list:
    """Reads a file based on its extension and returns a list of text chunks."""
    ext = os.path.splitext(file_path)[-1].lower()
    text = ""

    if ext == ".pdf":
        text = extract_pdf(file_path)
    elif ext in [".xls", ".xlsx", ".csv"]:
        text = extract_excel(file_path)
    elif ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"]:
        text = extract_image(file_path)
    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

    if not text.strip():
        print(f"[WARNING] No text extracted from {file_path}")
        return []

    return chunk_text(text)


# ─────────────────────────────────────────────────────────────────────
# Chunking WITH location metadata (page numbers / row ranges)
#
# `process_document_chunks` is the richer counterpart to `process_document`:
# it returns (text, meta) pairs so citations can point at *where* in the source
# a chunk came from (e.g. {"page": 3} for PDFs, {"rows": "16-30"} for tables).
# The meta dict is merged into each chunk's Document metadata at index time.
# `process_document` (plain strings) is kept for callers that don't need this.
# ─────────────────────────────────────────────────────────────────────
def process_document_chunks(file_path: str) -> List[Tuple[str, dict]]:
    """Read a file and return a list of (chunk_text, location_metadata) pairs."""
    ext = os.path.splitext(file_path)[-1].lower()

    if ext == ".pdf":
        chunks: List[Tuple[str, dict]] = []
        for page_no, page_text in _extract_pdf_pages(file_path):
            for piece in chunk_text(page_text):
                chunks.append((piece, {"page": page_no}))
        return chunks

    if ext in (".xls", ".xlsx", ".csv"):
        return _extract_excel_blocks(file_path)

    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"):
        text = extract_image(file_path)
        return [(piece, {}) for piece in chunk_text(text)] if text.strip() else []

    if ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        return [(piece, {}) for piece in chunk_text(text)] if text.strip() else []

    raise ValueError(f"Unsupported file extension: {ext}")


# ─────────────────────────────────────────────────────────────────────
# PDF extraction — text-based first, then OCR fallback
# ─────────────────────────────────────────────────────────────────────
def extract_pdf(file_path: str) -> str:
    """
    Extract text from a PDF.
    1st attempt: PyPDF2 (fast, works for text PDFs).
    2nd attempt: pdf2image + pytesseract (for scanned / handwritten PDFs).
    """
    text = _extract_pdf_text(file_path)

    # If we got very little text (< 50 chars total), it's likely an image-based PDF
    if len(text.strip()) < 50:
        print(f"[INFO] Text PDF extraction got very little text — trying OCR for {file_path}")
        text = _extract_pdf_via_ocr(file_path)

    return text


def _extract_pdf_pages(file_path: str) -> List[Tuple[int, str]]:
    """
    Extract text per page as (page_number, text), 1-indexed. Tries PyPDF2 first;
    if the whole document yields almost no text (image/scanned PDF), falls back
    to per-page OCR. Used by `process_document_chunks` so chunks can cite pages.
    """
    pages: List[Tuple[int, str]] = []
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                content = page.extract_text() or ""
                pages.append((i + 1, content))
    except Exception as e:
        print(f"[ERROR] PyPDF2 page extraction failed for {file_path}: {e}")

    total_chars = sum(len(t.strip()) for _, t in pages)
    if total_chars < 50:
        print(f"[INFO] Little text in {file_path} — trying per-page OCR.")
        ocr_pages = _extract_pdf_pages_via_ocr(file_path)
        if ocr_pages:
            return ocr_pages

    return [(n, t) for n, t in pages if t.strip()]


def _extract_pdf_pages_via_ocr(file_path: str) -> List[Tuple[int, str]]:
    """Per-page OCR for scanned/image PDFs → [(page_number, text), ...]."""
    if not _ocr_ready():
        print("[INFO] OCR disabled or unavailable — skipping OCR for this PDF "
              "(enable Balanced/Power mode and install Tesseract to OCR scanned files).")
        return []
    if not PDF2IMAGE_AVAILABLE:
        print("[WARNING] pdf2image not installed — cannot OCR this PDF.")
        return []
    out: List[Tuple[int, str]] = []
    try:
        images = convert_from_path(file_path, dpi=200)
        print(f"[INFO] OCR processing {len(images)} page(s) from {os.path.basename(file_path)}...")
        for i, img in enumerate(images):
            page_text = pytesseract.image_to_string(img, lang="eng")
            if page_text.strip():
                out.append((i + 1, page_text))
    except Exception as e:
        print(f"[ERROR] OCR failed for {file_path}: {e}")
    return out


def _extract_excel_blocks(file_path: str) -> List[Tuple[str, dict]]:
    """
    Same row-batching as `extract_excel`, but returns each 15-row block paired
    with its 1-indexed data-row range (e.g. {"rows": "16-30"}) for citations.
    """
    try:
        if file_path.endswith(".csv"):
            df = pd.read_csv(file_path, dtype=str).fillna("")
        else:
            df = pd.read_excel(file_path, dtype=str).fillna("")
        df.columns = [str(c).strip() for c in df.columns]

        ROWS_PER_CHUNK = 15
        blocks: List[Tuple[str, dict]] = []
        for start in range(0, len(df), ROWS_PER_CHUNK):
            batch = df.iloc[start:start + ROWS_PER_CHUNK]
            rows_text = []
            for _, row in batch.iterrows():
                parts = [f"{col}: {str(val).strip()}"
                         for col, val in row.items() if str(val).strip()]
                rows_text.append(" | ".join(parts))
            text = "\n".join(rows_text)
            if text.strip():
                blocks.append((text, {"rows": f"{start + 1}-{start + len(batch)}"}))
        return blocks
    except Exception as e:
        print(f"[ERROR] Excel/CSV block extraction failed: {e}")
        return []


def _extract_pdf_text(file_path: str) -> str:
    """Standard PyPDF2 text extraction."""
    text = ""
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                content = page.extract_text()
                if content:
                    text += content + "\n"
    except Exception as e:
        print(f"[ERROR] PyPDF2 failed for {file_path}: {e}")
    return text


def _extract_pdf_via_ocr(file_path: str) -> str:
    """
    Convert each PDF page to an image and run pytesseract OCR on it.
    Used for scanned documents, image PDFs, and handwritten forms.
    """
    if not _ocr_ready():
        print("[INFO] OCR disabled or unavailable — skipping OCR for this PDF.")
        return ""
    if not PDF2IMAGE_AVAILABLE:
        print("[WARNING] pdf2image not installed — cannot OCR this PDF. Run: pip install pdf2image")
        return ""

    text = ""
    try:
        # Convert PDF pages → PIL images (DPI 200 is a good balance of quality/speed)
        images = convert_from_path(file_path, dpi=200)
        print(f"[INFO] OCR processing {len(images)} page(s) from {os.path.basename(file_path)}...")
        for i, img in enumerate(images):
            page_text = pytesseract.image_to_string(img, lang="eng")
            if page_text.strip():
                text += f"--- Page {i + 1} ---\n{page_text}\n"
    except Exception as e:
        print(f"[ERROR] OCR failed for {file_path}: {e}")
    return text


# ─────────────────────────────────────────────────────────────────────
# Excel / CSV  —  row-by-row labelled text for accurate retrieval
# ─────────────────────────────────────────────────────────────────────
def extract_excel(file_path: str) -> str:
    """
    Convert every row into a labelled text block so that FAISS can find
    specific records by any field (ID, name, score, review, etc.).

    Example output for one row:
        Movie_ID: 100117 | Title: The Last S | Year: 2020 | Genre: Action |
        Country: South Korea | Audience_Score: 46 |
        Review: Better left for late-night cable TV.

    Rows are grouped in batches of 15 so each chunk keeps column context.
    """
    try:
        if file_path.endswith(".csv"):
            df = pd.read_csv(file_path, dtype=str).fillna("")
        else:
            df = pd.read_excel(file_path, dtype=str).fillna("")

        # Clean column names (strip whitespace)
        df.columns = [str(c).strip() for c in df.columns]

        ROWS_PER_CHUNK = 15          # tune if needed
        text_blocks = []

        for start in range(0, len(df), ROWS_PER_CHUNK):
            batch = df.iloc[start:start + ROWS_PER_CHUNK]
            rows_text = []
            for _, row in batch.iterrows():
                # "Col1: val1 | Col2: val2 | ..."
                parts = [f"{col}: {str(val).strip()}"
                         for col, val in row.items()
                         if str(val).strip()]
                rows_text.append(" | ".join(parts))
            text_blocks.append("\n".join(rows_text))

        return "\n\n".join(text_blocks)

    except Exception as e:
        print(f"[ERROR] Excel/CSV extraction failed: {e}")

        return ""


# ─────────────────────────────────────────────────────────────────────
# Image (JPG, PNG etc.) — direct pytesseract OCR
# ─────────────────────────────────────────────────────────────────────
def extract_image(file_path: str) -> str:
    """Use pytesseract OCR to extract text from image files."""
    if not _ocr_ready():
        print("[INFO] OCR disabled or unavailable — image text not extracted "
              "(enable Balanced/Power mode and install Tesseract for image OCR).")
        return ""
    try:
        img = Image.open(file_path)
        # Pre-process: convert to grayscale for better OCR accuracy
        img = img.convert("L")
        text = pytesseract.image_to_string(img, lang="eng")
        return text
    except Exception as e:
        print(f"[ERROR] Image OCR failed for {file_path}: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────
# Text chunking
# ─────────────────────────────────────────────────────────────────────
def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list:
    """Split long text into overlapping chunks for FAISS indexing."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
    )
    return splitter.split_text(text)
