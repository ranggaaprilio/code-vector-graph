"""Shared test fixtures and path constants.

`FIXTURES_DIR` is resolved from this file's location so tests work regardless of
the working directory pytest was launched from.
"""

from pathlib import Path

import pytest

# tests/manual/ holds scripts that download real multi-GB models and hit live
# services. Ignored here rather than via a relative --ignore in addopts, which
# only matched when pytest happened to be invoked from the repo root.
collect_ignore_glob = ["manual/*"]

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
PROJECT_ROOT = TESTS_DIR.parent


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT
