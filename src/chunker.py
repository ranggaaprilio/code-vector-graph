"""
Token-aware sliding window chunker using configurable tokenizer.
"""
from __future__ import annotations

import logging
from typing import List, Dict, Optional

from src.config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, TOKENIZER_NAME

logger = logging.getLogger(__name__)

_tokenizer_cache = None  # type: Optional["Tokenizer"]


class _DummyEncoding:
    def __init__(self, ids: List[int]):
        self.ids = ids


class _DummyTokenizer:
    def encode(self, text: str) -> _DummyEncoding:
        if text is None:
            return _DummyEncoding([])
        # Very simple whitespace-based tokenization for fallback
        tokens = [t for t in text.strip().split() if t != ""]
        return _DummyEncoding(list(range(len(tokens))))

    def decode(self, token_ids: List[int]) -> str:
        """Decode token ids back to text (reconstructs from original line)."""
        if not token_ids:
            return ""
        # For dummy tokenizer, we can't perfectly reconstruct, so return placeholder
        # The real tokenizer will handle this correctly
        return "word " * len(token_ids)


def load_tokenizer(tokenizer_name: str = "bert-base-uncased"):
    """Load a tokenizer by name with simple fallback.

    Cached for performance per tokenizer name. If the real tokenizer cannot
    be loaded (no network), a lightweight dummy tokenizer is used so tests
    can run offline.

    Args:
        tokenizer_name: Name of the tokenizer model to load (e.g., 'bert-base-uncased',
                       'jinaai/jina-code-embeddings-1.5b')

    Returns:
        Tokenizer instance or DummyTokenizer fallback
    """
    global _tokenizer_cache

    if not isinstance(_tokenizer_cache, dict):
        _tokenizer_cache = {}

    if tokenizer_name in _tokenizer_cache:
        return _tokenizer_cache[tokenizer_name]

    tokenizer = None
    try:
        from tokenizers import Tokenizer  # type: ignore
        from huggingface_hub import hf_hub_download

        tokenizer_path = hf_hub_download(
            repo_id=tokenizer_name,
            filename="tokenizer.json",
            local_files_only=True
        )
        tokenizer = Tokenizer.from_file(tokenizer_path)  # type: ignore
        logger.debug(f"Loaded tokenizer: {tokenizer_name}")
    except Exception:
        tokenizer = _DummyTokenizer()
        logger.debug(f"Using dummy tokenizer for: {tokenizer_name}")

    _tokenizer_cache[tokenizer_name] = tokenizer
    return tokenizer


def count_tokens(text: str, tokenizer) -> int:
    if not text:
        return 0
    encoding = tokenizer.encode(text)
    return len(encoding.ids)


def _split_long_line(line: str, chunk_size: int, tokenizer) -> List[str]:
    """Split a long line into chunks at token boundaries.

    For lines that exceed chunk_size tokens, split into multiple
    sub-chunks at token boundaries to ensure each sub-chunk fits.

    Args:
        line: The long line to split
        chunk_size: Maximum tokens per chunk
        tokenizer: Tokenizer to use for counting

    Returns:
        List of sub-line strings, each within chunk_size tokens
    """
    encoding = tokenizer.encode(line)
    token_ids = encoding.ids

    if len(token_ids) <= chunk_size:
        return [line]

    sub_chunks = []
    start = 0
    while start < len(token_ids):
        end = min(start + chunk_size, len(token_ids))
        sub_chunk_ids = token_ids[start:end]
        sub_chunk_text = tokenizer.decode(sub_chunk_ids)
        sub_chunks.append(sub_chunk_text)
        start = end

    return sub_chunks


def _line_token_counts(lines: List[str], tokenizer) -> List[int]:
    return [count_tokens(line, tokenizer) for line in lines]


def chunk_text(
    text: str,
    start_line: int,
    end_line: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    function_name: Optional[str] = None,
    file_path: str = "",
    language: str = "",
    total_chunks: int = 0,
    node_type: Optional[str] = None,
    class_name: Optional[str] = None,
    parent_function: Optional[str] = None,
    imports: Optional[list] = None,
    exports: Optional[list] = None,
    symbols_defined: Optional[list] = None,
    call_sites: Optional[list] = None,
    is_exported: bool = False,
    visibility: str = "unknown",
    decorators: Optional[list] = None,
    file_hash: str = "",
    tokenizer_name: str = "bert-base-uncased",
):
    """Split text into token-aware chunks with sliding window overlap.

    - Line-based chunking: accumulate lines until reaching chunk_size tokens.
    - No mid-line splitting. If a single line exceeds the chunk size, it forms
      its own chunk.
    - Sliding window overlap between consecutive chunks is ensured by reusing the
      last N lines that sum to at most chunk_overlap tokens.
    - Two-pass behavior: this function returns chunks; total_chunks is filled by the
      caller after counting.

    Args:
        tokenizer_name: Name of the tokenizer model to use for counting tokens.
                       Must match the tokenizer used by the embedding provider.
    """
    tokenizer = load_tokenizer(tokenizer_name)
    if not text:
        return []

    lines = text.splitlines()
    if not lines:
        return []

    line_token_counts = _line_token_counts(lines, tokenizer)

    # Calculate nesting depth
    nesting_depth = 0
    for line in lines:
        open_count = line.count('{') + line.count('(') + line.count('[')
        close_count = line.count('}') + line.count(')') + line.count(']')
        line_depth = open_count - close_count
        if line_depth > nesting_depth:
            nesting_depth = line_depth

    start_idx = 0
    end_idx = 0
    current_tokens = 0
    chunks: List[Dict] = []

    while end_idx < len(lines):
        if current_tokens + line_token_counts[end_idx] <= chunk_size:
            current_tokens += line_token_counts[end_idx]
            end_idx += 1
            continue

        # If a single line overflows the chunk size, split it at token boundaries
        if end_idx == start_idx:
            long_line = lines[start_idx]
            sub_chunks = _split_long_line(long_line, chunk_size, tokenizer)
            base_line_num = start_line + start_idx
            for sub_idx, sub_chunk in enumerate(sub_chunks):
                chunks.append(
                    {
                        "text": sub_chunk,
                        "metadata": {
                            "file_path": file_path,
                            "language": language,
                            "start_line": base_line_num,
                            "end_line": base_line_num,
                            "chunk_index": len(chunks) + 1,
                            "function_name": function_name,
                            "total_chunks": 0,
                            "node_type": node_type,
                            "class_name": class_name,
                            "parent_function": parent_function,
                            "imports": imports,
                            "exports": exports,
                            "symbols_defined": symbols_defined,
                            "call_sites": call_sites,
                            "is_exported": is_exported,
                            "visibility": visibility,
                            "decorators": decorators,
                            "file_hash": file_hash,
                        },
                    }
                )
            end_idx += 1
            start_idx = end_idx
            current_tokens = 0
            continue

        # Normal case: finalize current chunk and prepare overlap for next chunk
        chunk_lines = lines[start_idx:end_idx]
        chunk_text_segment = "\n".join(chunk_lines)
        cs = start_line + start_idx
        ce = start_line + end_idx - 1
        chunks.append(
            {
                "text": chunk_text_segment,
                "metadata": {
                    "file_path": file_path,
                    "language": language,
                    "start_line": cs,
                    "end_line": ce,
                    "chunk_index": len(chunks) + 1,
                    "function_name": function_name,
                    "total_chunks": 0,
                    "node_type": node_type,
                    "class_name": class_name,
                    "parent_function": parent_function,
                    "imports": imports,
                    "exports": exports,
                    "symbols_defined": symbols_defined,
                    "call_sites": call_sites,
                    "is_exported": is_exported,
                    "visibility": visibility,
                    "decorators": decorators,
                    "file_hash": file_hash,
                },
            }
        )

        # Compute overlap in lines for the next chunk
        overlap_lines = 0
        acc = 0
        j = end_idx - 1
        while j >= start_idx and acc + line_token_counts[j] <= chunk_overlap:
            acc += line_token_counts[j]
            overlap_lines += 1
            j -= 1
        if overlap_lines == 0:
            start_idx = end_idx
        else:
            start_idx = end_idx - overlap_lines
        current_tokens = acc
        # Continue without advancing end_idx here; the loop will try to fill more lines

    # Final remaining chunk
    if end_idx > start_idx:
        chunk_lines = lines[start_idx:end_idx]
        chunk_text_segment = "\n".join(chunk_lines)
        cs = start_line + start_idx
        ce = start_line + end_idx - 1
        chunks.append(
            {
                "text": chunk_text_segment,
                "metadata": {
                    "file_path": file_path,
                    "language": language,
                    "start_line": cs,
                    "end_line": ce,
                    "chunk_index": len(chunks) + 1,
                    "function_name": function_name,
                    "total_chunks": 0,
                    "node_type": node_type,
                    "class_name": class_name,
                    "parent_function": parent_function,
                    "imports": imports,
                    "exports": exports,
                    "symbols_defined": symbols_defined,
                    "call_sites": call_sites,
                    "is_exported": is_exported,
                    "visibility": visibility,
                    "decorators": decorators,
                    "file_hash": file_hash,
                },
            }
        )

    if not chunks:
        return []

    total = len(chunks)
    for idx in range(len(chunks)):
        chunks[idx]["metadata"]["total_chunks"] = total
        chunks[idx]["metadata"]["chunk_index"] = idx + 1

    return chunks


def chunk_file(parsed_result: Optional[Dict], file_path: str, language: str, tokenizer_name: str = "bert-base-uncased") -> List[Dict]:
    """Chunk the text produced by a parsed file result.

    parsed_result is expected to provide at least a 'text' field and line range.

    Args:
        parsed_result: Dictionary containing parsed file data
        file_path: Path to the source file
        language: Programming language of the file
        tokenizer_name: Name of the tokenizer model to use
    """
    if not parsed_result:
        return []
    text = parsed_result.get("text", "")
    start_line = parsed_result.get("start_line", 1)
    end_line = parsed_result.get("end_line", start_line)
    function_name = parsed_result.get("function_name", None)
    return chunk_text(
        text,
        start_line=start_line,
        end_line=end_line,
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
        function_name=function_name,
        file_path=file_path,
        language=language,
        tokenizer_name=tokenizer_name,
    )


__all__ = ["load_tokenizer", "count_tokens", "chunk_text", "chunk_file"]
