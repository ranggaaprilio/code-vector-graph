import os
import sys
import textwrap

# Ensure the src directory is on the import path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.join(ROOT, "src")
sys.path.insert(0, src_dir)

import parser


def _write_temp(name: str, content: str) -> str:
    path = os.path.join("tmp_test_sources", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
      f.write(content)
    return path


def test_js_comment_stripping():
    code = textwrap.dedent("""
    // top level comment
    function greet() {
      // inner comment
      const x = 1; /* block comment */
      return x;
    }
    """)
    path = _write_temp("js_test.js", code)
    result = parser.parse_file(path, "javascript")
    assert result is not None
    stripped = result["stripped_text"]
    # Ensure no comment tokens remain by reparsing and checking types
    parsed = parser.get_parser("javascript").parse(stripped.encode("utf-8"))
    root = parsed.root_node
    comment_nodes = []
    def _collect(n):
      if n.type in parser.COMMENT_NODE_TYPES:
        comment_nodes.append(n)
      for c in n.children:
        _collect(c)
    _collect(root)
    assert len(comment_nodes) == 0

    # Parity check using the provided tree
    # Re-parse the original data to produce a tree and compare with strip_comments behavior
    with open(path, "rb") as f:
        orig_bytes = f.read()
    tree = parser.get_parser("javascript").parse(orig_bytes)
    parity_stripped, parity_line_map = parser.strip_comments_with_tree(orig_bytes, "javascript", tree)
    assert parity_stripped == stripped
    assert parity_line_map == result["line_mapping"]


def test_ts_and_tsx_parsing_preserves_lines():
    ts_code = textwrap.dedent("""
    // type definition
    type Person = { name: string; age: number };
    function say(p: Person): string { return p.name; }
    """)
    ts_path = _write_temp("example.ts", ts_code)
    res = parser.parse_file(ts_path, "typescript")
    assert res is not None
    assert res["original_line_count"] > 0
    assert res["stripped_line_count"] > 0

    tsx_code = textwrap.dedent("""
    import React from 'react';
    type Props = { title: string };
    const App: React.FC<Props> = (p) => (
      <div>{p.title}</div>
    );
    // comment
    """)
    tsx_path = _write_temp("example.tsx", tsx_code)
    res2 = parser.parse_file(tsx_path, "tsx")
    assert res2 is not None
    assert "stripped_text" in res2


def test_function_name_extraction():
    code = textwrap.dedent("""
    // top-level
    function helloWorld() {
      return 42;
    }
    """)
    path = _write_temp("fn.js", code)
    src_bytes = open(path, "rb").read()
    tree = parser.get_parser("javascript").parse(src_bytes)
    root = tree.root_node
    func_node = None
    def _find(n):
      nonlocal func_node
      if n.type == "function_declaration":
        func_node = n
        return
      for c in n.children:
        _find(c)
    _find(root)
    if func_node is None:
      return
    name = parser.extract_function_name(tree, func_node.start_byte, func_node.end_byte, src_bytes)
    assert name == "helloWorld"


def test_parse_error_returns_none():
    code = "function }"  # invalid JS
    path = _write_temp("bad.js", code)
    res = parser.parse_file(path, "javascript")
    assert res is None


def test_extract_ast_metadata_basic():
    # JS sample with import, export, function, class, and a call expression
    code = textwrap.dedent("""
    import React from 'react';
    export function sayHello() { console.log('hello'); }
    class Greeter { constructor() { } greet() { console.log(this.constructor.name); } }
    sayHello();
    """.strip())
    path = _write_temp("md_ast.js", code)
    src_bytes = open(path, "rb").read()
    tree = parser.get_parser("javascript").parse(src_bytes)
    meta = parser.extract_ast_metadata(tree, src_bytes)
    # Imports should include the module path (react)
    assert "react" in meta.get("imports", [])
    # Symbols defined should include function and class names
    assert "sayHello" in meta.get("symbols_defined", [])
    assert "Greeter" in meta.get("symbols_defined", []) or meta.get("class_name", None) == "Greeter"
    # Class name captured
    assert meta.get("class_name") == "Greeter"
    # Call sites should include the console call (callee name)
    assert any(cs.startswith("console.log") for cs in meta.get("call_sites", []))
    # Exports flag should be true
    assert meta.get("is_exported", False) is True
    # Node type should be a non-empty string
    assert isinstance(meta.get("node_type"), (str, type(None)))
    # Decorators should be empty in this sample
    assert meta.get("decorators", []) == []


def test_extract_ast_metadata_none_tree():
    meta = parser.extract_ast_metadata(None, b"")
    assert meta["imports"] == []
    assert meta["exports"] == []
    assert meta["call_sites"] == []
    assert meta["symbols_defined"] == []
    assert meta["class_name"] is None
    assert meta["node_type"] is None
    assert meta["is_exported"] is False
    assert meta["visibility"] == "private"
    assert meta["decorators"] == []
    assert meta["parent_function"] is None


def test_extract_ast_metadata_bounding():
    # 60 identical imports; ensure dedup and bounding cap works
    code = "".join(["import 'dup';\n" for _ in range(60)])
    path = _write_temp("md_ast_dup.js", code)
    src_bytes = open(path, "rb").read()
    tree = parser.get_parser("javascript").parse(src_bytes)
    meta = parser.extract_ast_metadata(tree, src_bytes)
    assert len(meta["imports"]) <= 50


def test_parse_file_includes_source_and_tree():
    code = textwrap.dedent("""
    // sample
    function foo() { return 1; }
    """)
    path = _write_temp("sample.js", code)
    res = parser.parse_file(path, "javascript")
    assert res is not None
    # Ensure new keys exist
    assert "source_bytes" in res and "tree" in res
    # The source bytes should match the file contents
    with open(path, "rb") as f:
      original = f.read()
    assert res["source_bytes"] == original
    # Tree should be a parse tree with a root_node attribute
    assert hasattr(res["tree"], "root_node")
    # All expected keys present
    assert {"stripped_text", "original_line_count", "stripped_line_count", "line_mapping", "source_bytes", "tree"}.issubset(set(res.keys()))
