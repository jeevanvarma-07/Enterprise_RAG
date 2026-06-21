"""Tests for pure RAG helpers that don't require an LLM/network."""

from langchain_core.documents import Document

from services.generation import (
    reciprocal_rank_fusion,
    _scan_uploads_for_exact_match,
)


def _doc(text):
    return Document(page_content=text)


def test_rrf_ranks_consistently_top_docs_first():
    a, b, c = _doc("AAA"), _doc("BBB"), _doc("CCC")
    # `a` is top in both lists -> should win after fusion.
    lists = [[a, b, c], [a, c, b]]
    fused = reciprocal_rank_fusion(lists)
    assert fused[0].page_content == "AAA"
    assert {d.page_content for d in fused} == {"AAA", "BBB", "CCC"}


def test_rrf_dedupes_by_content():
    a1, a2 = _doc("SAME"), _doc("SAME")
    fused = reciprocal_rank_fusion([[a1], [a2]])
    assert len(fused) == 1


def test_exact_match_finds_numeric_id_in_csv(tmp_path):
    csv = tmp_path / "emp.csv"
    csv.write_text("EmpID,Role\n2529,Software Engineer\n9999,Manager\n", encoding="utf-8")
    out = _scan_uploads_for_exact_match("what is the role of employee 2529?", str(tmp_path))
    assert "Software Engineer" in out
    assert "Manager" not in out


def test_exact_match_returns_empty_without_numbers(tmp_path):
    csv = tmp_path / "emp.csv"
    csv.write_text("EmpID,Role\n2529,Software Engineer\n", encoding="utf-8")
    assert _scan_uploads_for_exact_match("who is the manager?", str(tmp_path)) == ""
