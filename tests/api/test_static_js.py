"""Run the frontend `node --test` suite for the static JS helpers.

Skips when Node is not installed; does not depend on the FastAPI fixtures in
tests/api/conftest.py.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC_JS_LIB = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "code_vector_graph"
    / "api"
    / "static"
    / "js"
    / "lib"
)


def test_static_js_unit_tests():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    assert STATIC_JS_LIB.is_dir(), f"missing {STATIC_JS_LIB}"

    result = subprocess.run(
        [node, "--test", str(STATIC_JS_LIB)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "node --test failed\n--- stdout ---\n"
        f"{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
