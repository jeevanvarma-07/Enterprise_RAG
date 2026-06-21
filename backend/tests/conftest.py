"""
Shared test setup.

Crucially, RAG_DATA_DIR is set to a throwaway temp directory BEFORE any app
module is imported, so config resolves all paths (vector store, SQLite db,
settings, models) inside it. Tests therefore never touch the developer's real
uploads / index / chat history.
"""

import os
import tempfile

# Must happen before `import config` anywhere — config reads RAG_DATA_DIR at import.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="rag_test_")
os.environ.setdefault("RAG_DATA_DIR", _TEST_DATA_DIR)

import pytest  # noqa: E402

import config  # noqa: E402


@pytest.fixture()
def tmp_csv(tmp_path):
    """A small CSV with a known number of rows for table/citation tests."""
    p = tmp_path / "people.csv"
    rows = ["id,role"] + [f"{i},Engineer{i}" for i in range(40)]
    p.write_text("\n".join(rows), encoding="utf-8")
    return p


@pytest.fixture()
def tmp_txt(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("alpha beta gamma\n" * 100, encoding="utf-8")
    return p


@pytest.fixture()
def restore_settings():
    """Snapshot settings before a test mutates them, restore after."""
    before = config.get_settings()
    yield
    config.save_settings(before)
