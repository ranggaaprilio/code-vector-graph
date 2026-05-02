"""Tests for scanner module."""

import os
import tempfile
import pytest
from pathlib import Path

from src.scanner import discover_files, is_binary, compute_file_hash, SKIP_DIRS


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestIsBinary:
    def test_binary_file_detected(self):
        binary_path = FIXTURES_DIR / "binary.bin"
        assert is_binary(binary_path) is True

    def test_text_file_not_binary(self):
        text_path = FIXTURES_DIR / "sample.js"
        assert is_binary(text_path) is False


class TestDiscoverFiles:
    def test_discovers_js_files(self):
        results = discover_files(str(FIXTURES_DIR))
        paths = [r["path"] for r in results]
        assert any("sample.js" in p for p in paths)

    def test_discovers_ts_files(self):
        results = discover_files(str(FIXTURES_DIR))
        paths = [r["path"] for r in results]
        assert any("sample.ts" in p for p in paths)

    def test_discovers_tsx_files(self):
        results = discover_files(str(FIXTURES_DIR))
        paths = [r["path"] for r in results]
        assert any("component.tsx" in p for p in paths)

    def test_returns_correct_metadata(self):
        results = discover_files(str(FIXTURES_DIR))
        sample_js = next(r for r in results if "sample.js" in r["path"])
        assert sample_js["extension"] == ".js"
        assert sample_js["language"] == "javascript"
        assert sample_js["grammar"] == "javascript"

        tsx = next(r for r in results if "component.tsx" in r["path"])
        assert tsx["extension"] == ".tsx"
        assert tsx["language"] == "tsx"
        assert tsx["grammar"] == "tsx"

    def test_skips_node_modules(self):
        results = discover_files(str(FIXTURES_DIR))
        paths = [r["path"] for r in results]
        assert not any("node_modules" in p for p in paths)

    def test_skips_binary_files(self):
        results = discover_files(str(FIXTURES_DIR))
        paths = [r["path"] for r in results]
        assert not any("binary.bin" in p for p in paths)

    def test_skips_unsupported_extensions(self):
        py_file = FIXTURES_DIR.parent.parent / "src" / "config.py"
        if py_file.exists():
            results = discover_files(str(FIXTURES_DIR.parent.parent))
            paths = [r["path"] for r in results]
            assert not any(p.endswith(".py") for p in paths)

    def test_results_sorted(self):
        results = discover_files(str(FIXTURES_DIR))
        paths = [r["path"] for r in results]
        assert paths == sorted(paths)


class TestSkipDirs:
    def test_skip_dirs_defined(self):
        assert "node_modules" in SKIP_DIRS
        assert ".git" in SKIP_DIRS
        assert "dist" in SKIP_DIRS
        assert "build" in SKIP_DIRS
        assert "__pycache__" in SKIP_DIRS
        assert ".venv" in SKIP_DIRS


class TestComputeFileHash:
    def test_hash_returns_16_chars(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".js") as f:
            f.write(b"test content")
            f.flush()
            h = compute_file_hash(Path(f.name))
        os.unlink(f.name)
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_same_for_same_content(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".js") as f1:
            f1.write(b"same content")
            f1.flush()
            h1 = compute_file_hash(Path(f1.name))
        with tempfile.NamedTemporaryFile(delete=False, suffix=".js") as f2:
            f2.write(b"same content")
            f2.flush()
            h2 = compute_file_hash(Path(f2.name))
        os.unlink(f1.name)
        os.unlink(f2.name)
        assert h1 == h2

    def test_hash_different_for_different_content(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".js") as f1:
            f1.write(b"content a")
            f1.flush()
            h1 = compute_file_hash(Path(f1.name))
        with tempfile.NamedTemporaryFile(delete=False, suffix=".js") as f2:
            f2.write(b"content b")
            f2.flush()
            h2 = compute_file_hash(Path(f2.name))
        os.unlink(f1.name)
        os.unlink(f2.name)
        assert h1 != h2

    def test_unreadable_file_returns_empty_string(self):
        h = compute_file_hash(Path("/nonexistent/file.js"))
        assert h == ""


class TestDiscoverFilesFileHash:
    def test_file_hash_key_present(self):
        results = discover_files(str(FIXTURES_DIR))
        assert len(results) > 0
        for r in results:
            assert "file_hash" in r
            assert len(r["file_hash"]) == 16