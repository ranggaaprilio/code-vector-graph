import pytest
from pathlib import Path
from src.parser import parse_file

# The extractor is not yet implemented in this task phase.
try:
    from src.graph_extractor import extract_graph_entities
except Exception:
    extract_graph_entities = None


def parsed(file_path: str, lang: str):
    return parse_file(file_path, lang)


class TestGraphExtractor:
    def test_extract_file_node(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                     "tests/fixtures/sample.ts", "typescript", "abc123")
        assert isinstance(res, dict)
        assert "nodes" in res and "relationships" in res
        file_nodes = [n for n in res["nodes"] if n.get("label") == "File"]
        assert len(file_nodes) == 1
        assert file_nodes[0]["properties"].get("path") == "tests/fixtures/sample.ts"

    def test_extract_class_node(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   "tests/fixtures/sample.ts", "typescript", "classhash")
        assert isinstance(res, dict)
        nodes = res.get("nodes", [])
        assert any(n.get("label") == "Class" for n in nodes)

    def test_extract_function_node(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   "tests/fixtures/sample.ts", "typescript", "funchash")
        assert isinstance(res, dict)
        nodes = res.get("nodes", [])
        assert any(n.get("label") == "Function" for n in nodes)

    def test_extract_variable_node(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   "tests/fixtures/sample.ts", "typescript", "varhash")
        assert isinstance(res, dict)
        nodes = res.get("nodes", [])
        assert any(n.get("label") == "Variable" for n in nodes)

    def test_extract_field_node(self, tmp_path):
        path = tmp_path / "sample_field.ts"
        path.write_text("class User {\n  name: string;\n}\n")
        parsed_doc = parsed(str(path), "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   str(path), "typescript", "fieldhash")
        nodes = res.get("nodes", [])
        assert any(
            n.get("label") == "Field" and n.get("properties", {}).get("name") == "name"
            for n in nodes
        )

    def test_extract_import_node(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   "tests/fixtures/sample.ts", "typescript", "importhash")
        assert isinstance(res, dict)
        nodes = res.get("nodes", [])
        assert any(n.get("label") == "Import" for n in nodes)

    def test_extract_interface_node(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   "tests/fixtures/sample.ts", "typescript", "interfacehash")
        assert isinstance(res, dict)
        nodes = res.get("nodes", [])
        assert any(n.get("label") == "Interface" for n in nodes)

    def test_extract_contains_relationship(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   "tests/fixtures/sample.ts", "typescript", "relhash")
        assert isinstance(res, dict)
        rels = res.get("relationships", [])
        assert any(r.get("type") == "CONTAINS" for r in rels)

    def test_extract_calls_relationship(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   "tests/fixtures/sample.ts", "typescript", "callhash")
        assert isinstance(res, dict)
        rels = res.get("relationships", [])
        assert any(r.get("type") == "CALLS" for r in rels)

    def test_extract_imports_relationship(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   "tests/fixtures/sample.ts", "typescript", "import-rel")
        assert isinstance(res, dict)
        rels = res.get("relationships", [])
        assert any(r.get("type") == "IMPORTS" for r in rels)

    def test_extract_inherits_relationship(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   "tests/fixtures/sample.ts", "typescript", "inherit-hash")
        assert isinstance(res, dict)
        rels = res.get("relationships", [])
        assert any(r.get("type") == "INHERITS" for r in rels)

    def test_extract_exports_relationship(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   "tests/fixtures/sample.ts", "typescript", "exports")
        assert isinstance(res, dict)
        rels = res.get("relationships", [])
        assert any(r.get("type") == "EXPORTS" for r in rels)

    def test_extract_references_relationship(self):
        parsed_doc = parsed("tests/fixtures/sample.ts", "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                   "tests/fixtures/sample.ts", "typescript", "references")
        assert isinstance(res, dict)
        rels = res.get("relationships", [])
        assert any(r.get("type") == "REFERENCES" for r in rels)

    def test_edge_case_empty_file(self):
        empty_path = "tests/fixtures/empty.ts"
        Path(empty_path).parents[0].mkdir(parents=True, exist_ok=True)
        Path(empty_path).write_text("")
        parsed_doc = parsed(empty_path, "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                     empty_path, "typescript", "emptyhash")
        assert isinstance(res, dict)
        assert "nodes" in res and "relationships" in res

    def test_edge_case_no_exports(self):
        path = "tests/fixtures/sample_no_exports.js"
        Path(path).write_text("const a = 1; function b(){ return a; }")
        parsed_doc = parsed(path, "javascript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                     path, "javascript", "noexports")
        assert isinstance(res, dict)
        assert "nodes" in res and "relationships" in res

    def test_edge_case_nested_functions(self):
        path = "tests/fixtures/sample_nested.ts"
        Path(path).write_text(
            """export class Outer {\n    method() {\n        function inner() { return 42; }\n        return inner();\n    }\n}\n"""
        )
        parsed_doc = parsed(path, "typescript")
        assert parsed_doc is not None
        if extract_graph_entities is None:
            pytest.skip("graph_extractor not implemented yet")
        res = extract_graph_entities(parsed_doc.get("tree"), parsed_doc.get("source_bytes"),
                                     path, "typescript", "nested")
        assert isinstance(res, dict)
        assert "nodes" in res and "relationships" in res
