"""Tests for text extraction + chunking, including location metadata."""

from openpyxl import Workbook

from services.document_processing import (
    chunk_text,
    process_document_chunks,
)


def test_chunk_text_splits_long_text():
    chunks = chunk_text("word " * 2000, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(isinstance(c, str) and c for c in chunks)


def test_txt_chunks_have_empty_meta(tmp_txt):
    out = process_document_chunks(str(tmp_txt))
    assert out, "expected at least one chunk"
    assert all(isinstance(t, str) for t, _ in out)
    assert all(m == {} for _, m in out)


def test_csv_blocks_tag_row_ranges(tmp_csv):
    out = process_document_chunks(str(tmp_csv))
    # 40 rows, 15 per block -> 3 blocks
    assert len(out) == 3
    metas = [m for _, m in out]
    assert metas == [{"rows": "1-15"}, {"rows": "16-30"}, {"rows": "31-40"}]
    # Column labels are preserved in the text for retrieval.
    assert "role:" in out[0][0]


def test_xlsx_blocks_tag_row_ranges(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["id", "role"])
    for i in range(20):
        ws.append([i, f"Analyst{i}"])
    p = tmp_path / "staff.xlsx"
    wb.save(p)

    out = process_document_chunks(str(p))
    assert len(out) == 2  # 20 rows -> 15 + 5
    assert [m for _, m in out] == [{"rows": "1-15"}, {"rows": "16-20"}]


def test_unsupported_extension_raises(tmp_path):
    p = tmp_path / "thing.xyz"
    p.write_text("data", encoding="utf-8")
    try:
        process_document_chunks(str(p))
        assert False, "expected ValueError"
    except ValueError:
        pass
