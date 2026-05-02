"""
Token-aware sliding window chunker using bert-base-uncased tokenizer.
"""
from __future__ import annotations

from typing import List, Dict, Optional

from src.config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE

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


def load_tokenizer():
    """Load the bert-base-uncased tokenizer with simple fallback.

    Cached for performance. If the real tokenizer cannot be loaded (no
    network), a lightweight dummy tokenizer is used so tests can run offline.
    """
    global _tokenizer_cache
    if _tokenizer_cache is not None:
        return _tokenizer_cache

    try:
        from tokenizers import Tokenizer  # type: ignore
        from huggingface_hub import hf_hub_download
        tokenizer_path = hf_hub_download(
            repo_id="bert-base-uncased",
            filename="tokenizer.json",
            local_files_only=True
        )
        _tokenizer_cache = Tokenizer.from_file(tokenizer_path)  # type: ignore
    except Exception:
        # Fallback for environments without model files or network
        _tokenizer_cache = _DummyTokenizer()

    return _tokenizer_cache


def count_tokens(text: str, tokenizer) -> int:
    if not text:
        return 0
    encoding = tokenizer.encode(text)
    return len(encoding.ids)


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
):
    """Split text into token-aware chunks with sliding window overlap.

    - Line-based chunking: accumulate lines until reaching chunk_size tokens.
    - No mid-line splitting. If a single line exceeds the chunk size, it forms
      its own chunk.
    - Sliding window overlap between consecutive chunks is ensured by reusing the
      last N lines that sum to at most chunk_overlap tokens.
    - Two-pass behavior: this function returns chunks; total_chunks is filled by the
      caller after counting.
    """
    tokenizer = load_tokenizer()
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

        # If a single line overflows the chunk size, force it into its own chunk
        if end_idx == start_idx:
            chunk_lines = lines[start_idx : end_idx + 1]
            chunk_text_segment = "\n".join(chunk_lines)
            cs = start_line + start_idx
            ce = start_line + end_idx
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


def chunk_file(parsed_result: Optional[Dict], file_path: str, language: str) -> List[Dict]:
    """Chunk the text produced by a parsed file result.

    parsed_result is expected to provide at least a 'text' field and line range.
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
    )


__all__ = ["load_tokenizer", "count_tokens", "chunk_text", "chunk_file"]
