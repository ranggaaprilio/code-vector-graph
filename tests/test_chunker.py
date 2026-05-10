import sys
import os
from typing import List, Dict

# Ensure the src package is importable during tests
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.join(root_dir, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
import chunker as chunker
from chunker import load_tokenizer, count_tokens, chunk_text, chunk_file, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP


def test_count_tokens_matches_encoder():
    tok = load_tokenizer()
    text = "The quick brown fox"
    c = count_tokens(text, tok)
    assert c == len(tok.encode(text).ids) if hasattr(tok, "encode") else c >= 0


def test_chunk_basic_line_preservation_and_bounds():
    tok = load_tokenizer()
    # Create 9 lines, each with a few tokens
    lines = ["word word word word word word" for _ in range(9)]
    text = "\n".join(lines)
    chunks = chunk_text(text, start_line=1, end_line=9, chunk_size=20, chunk_overlap=4, file_path="tests.py", language="python")

    assert isinstance(chunks, list)
    assert len(chunks) > 0

    # Check line preservation: no mid-line splitting
    for chunk in chunks:
        s = chunk["metadata"]["start_line"]
        e = chunk["metadata"]["end_line"]
        chunk_lines = chunk["text"].splitlines()
        assert len(chunk_lines) == (e - s + 1)
        # first and last lines must correspond to the original input lines
        assert chunk_lines[0] == lines[s - 1] or chunk_lines[0] == lines[s - 1].rstrip()
        assert chunk_lines[-1] == lines[e - 1] or chunk_lines[-1] == lines[e - 1].rstrip()

    # Check token bound per chunk
    for chunk in chunks:
        tcount = count_tokens(chunk["text"], tok)
        assert tcount <= 20  # respect chunk_size in test


def test_overlap_between_consecutive_chunks():
    tok = load_tokenizer()
    lines = ["word word word word" for _ in range(10)]  # 4 tokens per line (roughly)
    text = "\n".join(lines)
    chunks = chunk_text(text, start_line=1, end_line=10, chunk_size=12, chunk_overlap=6, file_path="x.py", language="python")
    assert len(chunks) >= 2
    for i in range(len(chunks) - 1):
        end_i = chunks[i]["metadata"]["end_line"]
        start_next = chunks[i + 1]["metadata"]["start_line"]
        overlap_lines = end_i - start_next + 1
        if overlap_lines > 0:
            overl1 = "\n".join(chunks[i]["text"].splitlines()[-overlap_lines:])
            overl2 = "\n".join(chunks[i + 1]["text"].splitlines()[:overlap_lines])
            assert overl1 == overl2
            assert count_tokens(overl1, tok) >= 0  # basic sanity


def test_empty_input_returns_empty():
    res = chunk_text("", start_line=1, end_line=0)
    assert res == []


def test_single_line_overflow_handling():
    tok = load_tokenizer()
    line = "word " * 100  # many tokens in a single line
    text = line.strip()
    chunks = chunk_text(text, start_line=1, end_line=1, chunk_size=20, chunk_overlap=4, file_path="f.py", language="py")
    # Long lines are now split into multiple chunks at token boundaries
    assert len(chunks) > 1
    # Each chunk should be within token limit
    for ch in chunks:
        assert ch["metadata"]["start_line"] == 1
        assert ch["metadata"]["end_line"] == 1
        token_count = count_tokens(ch["text"], tok)
        assert token_count <= 20


def test_chunk_file_integration():
    parsed = {"text": "a\nb\nc", "start_line": 1, "end_line": 3, "function_name": "myfunc"}
    res = chunk_file(parsed, file_path="example.py", language="python")
    assert isinstance(res, list)
    assert len(res) > 0
