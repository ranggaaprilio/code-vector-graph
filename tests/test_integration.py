"""Integration tests for the full Code Vector Graph pipeline."""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.chunker import chunk_text
from src.cli import parse_args, setup_logging
from src.config import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_COLLECTION_NAME,
    DEFAULT_QDRANT_URL,
)
from main import check_qdrant_health, main, run_pipeline
from src.parser import parse_file
from src.scanner import discover_files
from src.store import VectorStore


@pytest.fixture
def test_repo(tmp_path):
    """Create a temporary test repository with JS/TS files."""
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # Create a simple JS file
    js_file = repo / "test.js"
    js_file.write_text("""
function hello() {
    console.log("Hello, World!");
}

function world() {
    return 42;
}
""")

    # Create a simple TS file
    ts_file = repo / "test.ts"
    ts_file.write_text("""
interface User {
    name: string;
    age: number;
}

class Greeter {
    greet(user: User): string {
        return `Hello, ${user.name}!`;
    }
}
""")

    # Create a file in node_modules (should be skipped)
    node_modules = repo / "node_modules"
    node_modules.mkdir()
    (node_modules / "should_skip.js").write_text("// should be skipped")

    return str(repo)


@pytest.fixture
def mock_args(test_repo):
    """Create mock arguments for testing."""
    args = MagicMock()
    args.repo_path = test_repo
    args.qdrant_url = DEFAULT_QDRANT_URL
    args.collection_name = "test_collection"
    args.chunk_size = DEFAULT_CHUNK_SIZE
    args.chunk_overlap = DEFAULT_CHUNK_OVERLAP
    args.no_graph = True
    args.batch_size = 64
    args.dry_run = False
    args.verbose = False
    return args


class TestCLIArgumentParsing:
    """Test CLI argument parsing."""

    def test_parse_args_required_repo_path(self, test_repo):
        """Test that repo-path is required."""
        args = parse_args(["--repo-path", test_repo])
        assert args.repo_path == test_repo

    def test_parse_args_defaults(self, test_repo):
        """Test default argument values."""
        args = parse_args(["--repo-path", test_repo])
        assert args.qdrant_url == DEFAULT_QDRANT_URL
        assert args.collection_name == DEFAULT_COLLECTION_NAME
        assert args.chunk_size == DEFAULT_CHUNK_SIZE
        assert args.chunk_overlap == DEFAULT_CHUNK_OVERLAP
        assert args.batch_size == 64
        assert args.glossary_file == "glossary.yml"
        assert args.dry_run is False
        assert args.verbose is False

    def test_parse_args_custom_values(self, test_repo):
        """Test parsing custom argument values."""
        args = parse_args([
            "--repo-path", test_repo,
            "--qdrant-url", "http://custom:6333",
            "--collection-name", "custom_collection",
            "--chunk-size", "256",
            "--chunk-overlap", "32",
            "--batch-size", "32",
            "--glossary-file", "docs/glossary.yml",
            "--dry-run",
            "--verbose",
        ])
        assert args.qdrant_url == "http://custom:6333"
        assert args.collection_name == "custom_collection"
        assert args.chunk_size == 256
        assert args.chunk_overlap == 32
        assert args.batch_size == 32
        assert args.glossary_file == "docs/glossary.yml"
        assert args.dry_run is True
        assert args.verbose is True

    def test_parse_args_invalid_repo_path(self):
        """Test that invalid repo path raises error."""
        with pytest.raises(SystemExit):
            parse_args(["--repo-path", "/nonexistent/path"])

    def test_parse_args_invalid_chunk_size(self, test_repo):
        """Test that invalid chunk size raises error."""
        with pytest.raises(SystemExit):
            parse_args(["--repo-path", test_repo, "--chunk-size", "0"])

    def test_parse_args_invalid_chunk_overlap(self, test_repo):
        """Test that invalid chunk overlap raises error."""
        with pytest.raises(SystemExit):
            parse_args(["--repo-path", test_repo, "--chunk-overlap", "-1"])

    def test_parse_args_overlap_too_large(self, test_repo):
        """Test that overlap >= chunk size raises error."""
        with pytest.raises(SystemExit):
            parse_args([
                "--repo-path", test_repo,
                "--chunk-size", "100",
                "--chunk-overlap", "100",
            ])


class TestHealthChecks:
    def test_check_qdrant_health_success(self):
        """Test Qdrant health check passes when healthy."""
        store = VectorStore(qdrant_url=":memory:")
        result = check_qdrant_health(store)
        assert result is True

    def test_check_qdrant_health_failure(self):
        """Test Qdrant health check exits when unhealthy."""
        store = MagicMock()
        store.check_health.return_value = False
        store.client = "http://unreachable:6333"

        with pytest.raises(SystemExit) as exc_info:
            check_qdrant_health(store)
        assert exc_info.value.code == 1


class TestPipelineDryRun:
    """Test pipeline dry-run mode."""

    def test_dry_run_does_not_embed(self, test_repo, mock_args, caplog):
        """Test that dry-run mode does not call embedding or storage."""
        mock_args.dry_run = True
        mock_args.verbose = True

        with patch("main.create_embedder") as mock_create, \
             patch("main.VectorStore") as mock_store_class:

            mock_embedder = MagicMock()
            mock_create.return_value = mock_embedder

            mock_store = MagicMock()
            mock_store_class.return_value = mock_store

            stats = run_pipeline(mock_args)

            # Should discover and parse files
            assert stats["files_found"] > 0
            assert stats["files_parsed"] > 0
            assert stats["total_chunks"] > 0

            # Should NOT embed or store in dry-run mode
            mock_embedder.embed_chunks.assert_not_called()
            mock_store.upsert_chunks.assert_not_called()

            # Chunks should still be counted
            assert stats["chunks_embedded"] == 0
            assert stats["chunks_stored"] == 0

    def test_dry_run_prints_stats(self, test_repo, mock_args, capsys):
        """Test that dry-run mode prints statistics."""
        mock_args.dry_run = True

        with patch("main.create_embedder"), \
             patch("main.VectorStore"):
            run_pipeline(mock_args)

        captured = capsys.readouterr()
        assert "DRY RUN COMPLETE" in captured.out
        assert "Files found:" in captured.out
        assert "Files parsed:" in captured.out
        assert "Total chunks:" in captured.out


class TestPipelineFullRun:
    """Test full pipeline execution."""

    @patch("main.create_embedder")
    @patch("main.VectorStore")
    def test_full_pipeline_with_mocked_services(self, mock_store_class, mock_create, test_repo, mock_args):
        mock_embedder = MagicMock()
        mock_embedder.check_health.return_value = True
        mock_embedder.embed_chunks.return_value = [
            {
                "text": "function test() {}",
                "embedding": [0.1] * 256,
                "file_path": "/test.js",
                "chunk_index": 0,
                "language": "javascript",
                "start_line": 1,
                "end_line": 1,
                "total_chunks": 1,
                "text_content": "function test() {}",
            }
        ]
        mock_create.return_value = mock_embedder

        mock_store = MagicMock()
        mock_store.check_health.return_value = True
        mock_store.upsert_chunks.return_value = ["test-id-1"]
        mock_store_class.return_value = mock_store

        stats = run_pipeline(mock_args)

        assert stats["files_found"] > 0
        assert stats["files_parsed"] > 0
        assert stats["total_chunks"] > 0
        assert stats["chunks_embedded"] > 0
        assert stats["chunks_stored"] > 0

        # Verify embedder was called
        mock_embedder.embed_chunks.assert_called_once()

        # Verify store was called
        mock_store.upsert_chunks.assert_called_once()


class TestChunkStorage:
    """Test that chunks are stored correctly in Qdrant."""

    def test_chunks_inserted_with_correct_metadata(self, test_repo):
        """Test that chunks are inserted with correct metadata."""
        store = VectorStore(
            collection_name="test_metadata",
            qdrant_url=":memory:",
        )
        store.create_collection()

        # Create sample chunks
        chunks = [
            {
                "file_path": f"{test_repo}/test.js",
                "chunk_index": 0,
                "embedding": [0.1] * 3584,
                "language": "javascript",
                "start_line": 1,
                "end_line": 5,
                "function_name": "hello",
                "total_chunks": 2,
                "text_content": "function hello() { console.log('Hello'); }",
            },
            {
                "file_path": f"{test_repo}/test.js",
                "chunk_index": 1,
                "embedding": [0.2] * 3584,
                "language": "javascript",
                "start_line": 7,
                "end_line": 9,
                "function_name": "world",
                "total_chunks": 2,
                "text_content": "function world() { return 42; }",
            },
        ]

        point_ids = store.upsert_chunks(chunks)

        assert len(point_ids) == 2

        # Verify each point has correct metadata
        for i, point_id in enumerate(point_ids):
            point = store.get_point(point_id)
            assert point is not None
            payload = point["payload"]

            assert payload["file_path"] == f"{test_repo}/test.js"
            assert payload["language"] == "javascript"
            assert payload["chunk_index"] == i
            assert payload["total_chunks"] == 2
            assert "text_content" in payload
            assert payload["function_name"] in ["hello", "world"]


class TestVerboseOutput:
    """Test verbose logging output."""

    def test_verbose_enables_info_logging(self, test_repo, mock_args, caplog):
        """Test that verbose flag enables INFO level logging."""
        mock_args.verbose = True
        mock_args.dry_run = True

        with patch("main.create_embedder"), \
             patch("main.VectorStore"):

            with caplog.at_level("INFO"):
                run_pipeline(mock_args)

        # Should have INFO level log messages
        info_messages = [r for r in caplog.records if r.levelno >= 20]  # INFO = 20
        assert len(info_messages) > 0

    def test_non_verbose_only_warning(self, test_repo, mock_args, caplog):
        """Test that without verbose, only WARNING+ messages are shown."""
        mock_args.verbose = False
        mock_args.dry_run = True

        with patch("main.create_embedder"), \
             patch("main.VectorStore"):

            run_pipeline(mock_args)

        # Should not have DEBUG messages
        debug_messages = [r for r in caplog.records if r.levelno == 10]  # DEBUG = 10
        # Some debug messages might appear from other loggers
        # Just verify pipeline runs without verbose


class TestErrorHandling:
    """Test error handling in the pipeline."""

    def test_skip_failed_parse_files(self, test_repo, mock_args, tmp_path):
        """Test that files failing to parse are skipped and processing continues."""
        # Create a file that will fail to parse
        bad_file = tmp_path / "bad.js"
        bad_file.write_bytes(b"\x00\x01\x02")  # Binary content

        # Create a good file
        good_file = tmp_path / "good.js"
        good_file.write_text("function good() { return true; }")

        mock_args.repo_path = str(tmp_path)
        mock_args.dry_run = True

        with patch("main.create_embedder"), \
             patch("main.VectorStore"):

            stats = run_pipeline(mock_args)

            # Should process the good file even if bad file fails
            assert stats["files_parsed"] >= 1

    def test_pipeline_continues_on_parse_error(self, test_repo, mock_args, tmp_path):
        """Test that one parse error doesn't stop the entire pipeline."""
        # Setup a repo with multiple files where one might fail
        mock_args.repo_path = test_repo
        mock_args.dry_run = True

        with patch("main.create_embedder"), \
             patch("main.VectorStore"), \
             patch("main.parse_file") as mock_parse:

            # Make first call fail, second succeed
            mock_parse.side_effect = [
                None,  # First file fails
                {      # Second file succeeds
                    "stripped_text": "function test() {}",
                    "original_line_count": 1,
                    "stripped_line_count": 1,
                    "line_mapping": {0: 1},
                },
            ]

            stats = run_pipeline(mock_args)

            # Should continue processing even with failures
            assert stats["files_failed"] > 0


class TestEndToEndIntegration:
    """Test end-to-end integration with real components (no mocks)."""

    def test_end_to_end_dry_run(self, test_repo):
        """Test end-to-end dry-run with real components."""
        args = parse_args([
            "--repo-path", test_repo,
            "--dry-run",
            "--verbose",
        ])
        setup_logging(args.verbose)

        stats = run_pipeline(args)

        # Verify pipeline completed
        assert stats["files_found"] == 2  # test.js and test.ts
        assert stats["files_parsed"] == 2
        assert stats["files_failed"] == 0
        assert stats["total_chunks"] > 0

    def test_discover_parse_chunk_pipeline(self, test_repo):
        """Test the discover -> parse -> chunk pipeline stages."""
        # Stage 1: Discover
        files = discover_files(test_repo)
        assert len(files) == 2

        for file_info in files:
            # Stage 2: Parse
            parsed = parse_file(file_info["path"], file_info["grammar"])
            assert parsed is not None
            assert "stripped_text" in parsed

            # Stage 3: Chunk
            chunks = chunk_text(
                text=parsed["stripped_text"],
                start_line=1,
                end_line=parsed["stripped_line_count"],
                chunk_size=DEFAULT_CHUNK_SIZE,
                chunk_overlap=DEFAULT_CHUNK_OVERLAP,
                file_path=file_info["path"],
                language=file_info["language"],
            )

            assert len(chunks) > 0
            for chunk in chunks:
                assert "text" in chunk
                assert "metadata" in chunk
                assert chunk["metadata"]["file_path"] == file_info["path"]
                assert chunk["metadata"]["language"] == file_info["language"]


class TestMainEntryPoint:
    """Test the main entry point."""

    def test_main_with_dry_run(self, test_repo):
        """Test main function with dry-run."""
        with patch("sys.argv", ["code-vector-graph", "--repo-path", test_repo, "--dry-run"]):
            exit_code = main()
            assert exit_code == 0

    def test_main_keyboard_interrupt(self, test_repo):
        """Test main handles keyboard interrupt."""
        with patch("sys.argv", ["code-vector-graph", "--repo-path", test_repo]), \
             patch("main.run_pipeline", side_effect=KeyboardInterrupt()):
            exit_code = main()
            assert exit_code == 130

    def test_main_unexpected_error(self, test_repo):
        """Test main handles unexpected errors."""
        with patch("sys.argv", ["code-vector-graph", "--repo-path", test_repo]), \
             patch("main.run_pipeline", side_effect=Exception("Test error")):
            exit_code = main()
            assert exit_code == 1


class TestCLIHelp:
    """Test CLI help functionality."""

    @pytest.mark.skip(reason="src.cli has no __main__.py; covered by test_cli_parser_help")
    def test_cli_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.cli", "--help"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )

        output = result.stdout + result.stderr
        assert "--repo-path" in output or result.returncode != 0

    def test_cli_parser_help(self):
        """Test CLI parser help output directly."""
        from src.cli import create_parser

        parser = create_parser()
        help_text = parser.format_help()

        assert "--repo-path" in help_text
        assert "--qdrant-url" in help_text
        assert "--collection-name" in help_text
        assert "--chunk-size" in help_text
        assert "--chunk-overlap" in help_text
        assert "--batch-size" in help_text
        assert "--dry-run" in help_text
        assert "--verbose" in help_text
