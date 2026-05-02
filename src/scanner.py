"""JS/TS/TSX file scanner with directory skipping and binary detection."""

import hashlib
import os
from pathlib import Path

from src.config import SUPPORTED_EXTENSIONS

SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv"}


def is_binary(file_path: Path) -> bool:
    """Check if file is binary by looking for null bytes in first 8192 bytes."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except (OSError, IOError):
        return True


def is_utf8(file_path: Path) -> bool:
    """Check if file can be decoded as UTF-8."""
    try:
        with open(file_path, "rb") as f:
            f.read(8192)
        return True
    except UnicodeDecodeError:
        return False


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file content, returning first 16 hex characters."""
    try:
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()[:16]
    except (OSError, IOError, PermissionError, FileNotFoundError):
        return ""


def discover_files(repo_path: str) -> list[dict]:
    """
    Discover JS/TS/TSX files in repository.

    Args:
        repo_path: Path to repository root

    Returns:
        List of dicts with keys: path, extension, language, grammar
    """
    results = []
    repo = Path(repo_path)

    for root, dirs, files in os.walk(repo):
        # Filter out directories to skip (in-place modification affects os.walk)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for filename in files:
            file_path = Path(root) / filename
            ext = file_path.suffix.lower()

            # Only process supported extensions
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            # Skip binary files
            if is_binary(file_path):
                continue

            # Skip files that fail UTF-8 decode
            if not is_utf8(file_path):
                continue

            info = SUPPORTED_EXTENSIONS[ext]
            file_hash = compute_file_hash(file_path)
            results.append({
                "path": str(file_path),
                "extension": ext,
                "language": info["language"],
                "grammar": info["grammar"],
                "file_hash": file_hash,
            })

    # Sort by file path for consistent ordering
    results.sort(key=lambda x: x["path"])
    return results