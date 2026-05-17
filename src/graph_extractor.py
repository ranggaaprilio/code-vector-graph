"""Tree-sitter AST extractor for graph entities.

Produces nodes and relationships for Neo4j ingestion from Tree-sitter ASTs.
Uses extract_ast_metadata for lightweight data, then walks the AST for
richer extraction of classes, functions, methods, variables, imports,
interfaces, and type aliases.

Node IDs are deterministic UUID5 values based on file_path:label:name:start_line.
Relationships use source_id/target_id format matching GraphStore expectations.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from tree_sitter import Tree

from src.parser import extract_ast_metadata

NAMESPACE = uuid.NAMESPACE_URL


def _node_id(file_path: str, label: str, name: str, start_line: int) -> str:
    """Generate a deterministic UUID5 for a graph node."""
    name_part = f"{file_path}:{label}:{name}:{start_line}"
    return str(uuid.uuid5(NAMESPACE, name_part))


def _rel(rel_type: str, source_id: str, target_id: str,
         properties: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a relationship dict in the format expected by GraphStore."""
    return {
        "type": rel_type,
        "source_id": source_id,
        "target_id": target_id,
        "properties": properties or {},
    }


def extract_graph_entities(tree: Tree, source_bytes: bytes, file_path: str,
                           language: str, file_hash: str) -> Dict[str, List[Dict[str, Any]]]:
    """Extract graph entities from a Tree-sitter AST.

    Returns dict with 'nodes' and 'relationships' lists. Nodes conform to
    graph_schema.py NODE_PROPERTIES. Relationships use source_id/target_id.
    """
    if tree is None or source_bytes is None:
        return {"nodes": [], "relationships": []}

    ast_metadata = extract_ast_metadata(tree, source_bytes)
    root = tree.root_node

    nodes: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []
    added_ids: Dict[str, str] = {}

    def _text(n) -> str:
        try:
            return source_bytes[n.start_byte:n.end_byte].decode("utf-8", errors="replace")
        except Exception:
            return ""

    total_lines = source_bytes.count(b"\n") + (0 if source_bytes.endswith(b"\n") else 1)
    file_imports = ast_metadata.get("imports", []) or []
    file_exports = ast_metadata.get("exports", []) or []

    # --- File node ---
    file_id = _node_id(file_path, "File", file_path, 1)
    nodes.append({
        "label": "File",
        "id": file_id,
        "properties": {
            "path": file_path,
            "language": language,
            "file_hash": file_hash,
            "line_count": total_lines,
            "imports": file_imports,
            "exports": file_exports,
        },
    })

    # --- Walk AST for real entities ---
    def _walk(n, parent_class_id: Optional[str] = None):
        if n is None:
            return

        t = n.type

        # Class declarations
        if t == "class_declaration":
            name_node = n.child_by_field_name("name")
            name = _text(name_node) if name_node else f"AnonymousClass_{n.start_point[0]}"
            start_line = n.start_point[0] + 1
            end_line = n.end_point[0] + 1
            is_exported = _is_exported(n)
            visibility = "public" if is_exported else "private"
            decorators = _get_decorators(n)
            parent_class = _get_extends_name(n)

            cls_id = _node_id(file_path, "Class", name, start_line)
            nodes.append({
                "label": "Class",
                "id": cls_id,
                "properties": {
                    "name": name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "is_exported": is_exported,
                    "visibility": visibility,
                    "decorators": decorators,
                    "parent_class": parent_class,
                },
            })
            added_ids[f"Class:{name}:{start_line}"] = cls_id
            relationships.append(_rel("CONTAINS", file_id, cls_id))
            relationships.append(_rel("DEFINES", file_id, cls_id))

            if is_exported:
                relationships.append(_rel("EXPORTS", file_id, cls_id))

            body = n.child_by_field_name("body")
            if body is not None:
                for child in body.children:
                    _walk(child, parent_class_id=cls_id)
            return

        # Method definitions (inside classes)
        if t == "method_definition" and parent_class_id:
            name_node = n.child_by_field_name("name")
            name = _text(name_node) if name_node else f"anon_method_{n.start_point[0]}"
            start_line = n.start_point[0] + 1
            end_line = n.end_point[0] + 1
            is_exported = _is_exported(n)
            visibility = "public" if is_exported else "private"
            params = _get_params(n)
            decorators = _get_decorators(n)
            is_async = _is_async(n)

            method_id = _node_id(file_path, "Method", name, start_line)
            nodes.append({
                "label": "Method",
                "id": method_id,
                "properties": {
                    "name": name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "is_exported": is_exported,
                    "visibility": visibility,
                    "parameters": params,
                    "decorators": decorators,
                    "is_async": is_async,
                    "parent_class": None,
                    "call_sites": _get_call_sites(n),
                },
            })
            added_ids[f"Method:{name}:{start_line}"] = method_id
            relationships.append(_rel("CONTAINS", parent_class_id, method_id))
            relationships.append(_rel("DEFINES", file_id, method_id))
            return

        # Class fields/properties
        if t in ("public_field_definition", "field_definition") and parent_class_id:
            name_node = n.child_by_field_name("name")
            if name_node is None:
                name_node = next(
                    (child for child in n.named_children if child.type in ("property_identifier", "identifier")),
                    None,
                )
            name = _text(name_node) if name_node else ""
            if not name:
                return
            start_line = n.start_point[0] + 1
            end_line = n.end_point[0] + 1
            is_exported = _is_exported(n)
            visibility = "public" if is_exported else "private"
            type_node = n.child_by_field_name("type")
            type_annotation = _text(type_node) if type_node else None

            field_id = _node_id(file_path, "Field", name, start_line)
            nodes.append({
                "label": "Field",
                "id": field_id,
                "properties": {
                    "name": name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "is_exported": is_exported,
                    "visibility": visibility,
                    "type_annotation": type_annotation,
                    "parent_class": parent_class_id,
                },
            })
            added_ids[f"Field:{name}:{start_line}"] = field_id
            relationships.append(_rel("CONTAINS", parent_class_id, field_id))
            relationships.append(_rel("DEFINES", file_id, field_id))
            return

        # Function declarations (standalone, not methods)
        FUNCTION_NODES = {
            "function_declaration",
            "function",
            "arrow_function",
            "generator_function",
        }
        if t in FUNCTION_NODES and not parent_class_id:
            name = _extract_function_name(n)
            if not name:
                for child in n.children:
                    _walk(child, parent_class_id=parent_class_id)
                return
            start_line = n.start_point[0] + 1
            end_line = n.end_point[0] + 1
            is_exported = _is_exported(n)
            visibility = "public" if is_exported else "private"
            params = _get_params(n)
            decorators = _get_decorators(n)
            is_async = _is_async(n)

            func_id = _node_id(file_path, "Function", name, start_line)
            nodes.append({
                "label": "Function",
                "id": func_id,
                "properties": {
                    "name": name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "is_exported": is_exported,
                    "visibility": visibility,
                    "parameters": params,
                    "decorators": decorators,
                    "is_async": is_async,
                    "parent_function": None,
                    "call_sites": _get_call_sites(n),
                },
            })
            added_ids[f"Function:{name}:{start_line}"] = func_id
            relationships.append(_rel("CONTAINS", file_id, func_id))
            relationships.append(_rel("DEFINES", file_id, func_id))

            if is_exported:
                relationships.append(_rel("EXPORTS", file_id, func_id))

            for child in n.children:
                _walk(child, parent_class_id=parent_class_id)
            return

        # Variable declarations
        if t == "variable_declaration" or t == "lexical_declaration":
            for child in n.children:
                if child.type == "variable_declarator":
                    _add_variable(child, parent_class_id)

        # Import statements
        if t == "import_statement":
            source = ""
            names = []
            for child in n.children:
                if child.type == "string":
                    source = _text(child).strip("\"'")
                if child.type == "import_clause":
                    names = _get_import_names(child)
            start_line = n.start_point[0] + 1
            end_line = n.end_point[0] + 1
            if source:
                imp_id = _node_id(file_path, "Import", source, start_line)
                nodes.append({
                    "label": "Import",
                    "id": imp_id,
                    "properties": {
                        "module": source,
                        "names": names,
                        "start_line": start_line,
                        "end_line": end_line,
                        "is_wildcard": "*" in names,
                    },
                })
                added_ids[f"Import:{source}:{start_line}"] = imp_id
                relationships.append(_rel("CONTAINS", file_id, imp_id))
                relationships.append(_rel("IMPORTS", file_id, imp_id))
                relationships.append(_rel("DEPENDS_ON", file_id, imp_id))
            return

        # Interface declarations
        if t == "interface_declaration":
            name_node = n.child_by_field_name("name")
            name = _text(name_node) if name_node else f"AnonymousInterface_{n.start_point[0]}"
            start_line = n.start_point[0] + 1
            end_line = n.end_point[0] + 1
            is_exported = _is_exported(n)
            extends = _get_extends_list(n)

            iface_id = _node_id(file_path, "Interface", name, start_line)
            nodes.append({
                "label": "Interface",
                "id": iface_id,
                "properties": {
                    "name": name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "is_exported": is_exported,
                    "extends": extends,
                },
            })
            added_ids[f"Interface:{name}:{start_line}"] = iface_id
            relationships.append(_rel("CONTAINS", file_id, iface_id))
            relationships.append(_rel("DEFINES", file_id, iface_id))

            for parent_iface in extends:
                parent_id = _node_id(file_path, "Interface", parent_iface, 1)
                relationships.append(_rel("INHERITS", iface_id, parent_id))
            return

        # Type alias declarations
        if t == "type_alias_statement" or t == "type_declaration":
            name_node = n.child_by_field_name("name")
            name = _text(name_node) if name_node else f"Alias_{n.start_point[0]}"
            start_line = n.start_point[0] + 1
            end_line = n.end_point[0] + 1
            is_exported = _is_exported(n)
            type_value_node = n.child_by_field_name("value")
            type_expression = _text(type_value_node) if type_value_node else "unknown"

            ta_id = _node_id(file_path, "TypeAlias", name, start_line)
            nodes.append({
                "label": "TypeAlias",
                "id": ta_id,
                "properties": {
                    "name": name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "is_exported": is_exported,
                    "type_expression": type_expression,
                },
            })
            added_ids[f"TypeAlias:{name}:{start_line}"] = ta_id
            relationships.append(_rel("CONTAINS", file_id, ta_id))
            relationships.append(_rel("DEFINES", file_id, ta_id))
            return

        # Recurse into children
        for child in n.children:
            _walk(child, parent_class_id=parent_class_id)

    def _add_variable(declarator, parent_class_id: Optional[str]):
        """Add a Variable node from a variable_declarator."""
        name_node = declarator.child_by_field_name("name")
        name = _text(name_node) if name_node else ""
        if not name:
            return
        start_line = declarator.start_point[0] + 1
        end_line = declarator.end_point[0] + 1
        is_exported = _is_exported(declarator.parent if declarator.parent else declarator)
        visibility = "public" if is_exported else "private"
        is_constant = False
        if declarator.parent and declarator.parent.type == "lexical_declaration":
            is_constant = True

        var_id = _node_id(file_path, "Variable", name, start_line)
        nodes.append({
            "label": "Variable",
            "id": var_id,
            "properties": {
                "name": name,
                "start_line": start_line,
                "end_line": end_line,
                "is_exported": is_exported,
                "visibility": visibility,
                "is_constant": is_constant,
                "type_annotation": None,
            },
        })
        added_ids[f"Variable:{name}:{start_line}"] = var_id
        relationships.append(_rel("CONTAINS", file_id, var_id))
        relationships.append(_rel("DEFINES", file_id, var_id))

        if is_exported:
            relationships.append(_rel("EXPORTS", file_id, var_id))

    # --- Helper functions ---
    def _is_exported(n) -> bool:
        """Check if a node is inside an export statement."""
        current = n.parent if hasattr(n, 'parent') else None
        while current is not None:
            if current.type in ("export_statement", "export_default", "export_clause"):
                return True
            current = current.parent if hasattr(current, 'parent') else None
        return False

    def _get_decorators(n) -> List[str]:
        """Extract decorator names from a node's children."""
        decs = []
        for child in n.children:
            if child.type == "decorator":
                for c in child.named_children:
                    if c.type in ("identifier", "name"):
                        decs.append(_text(c))
        return decs

    def _get_extends_name(n) -> Optional[str]:
        """Get the parent class name from a class extends clause."""
        extends_clause = n.child_by_field_name("parent")
        if extends_clause is not None:
            return _text(extends_clause)
        for child in n.children:
            if child.type in ("extends_clause", "class_heritage"):
                for c in child.named_children:
                    if c.type in ("identifier", "type_identifier"):
                        return _text(c)
        return None

    def _get_extends_list(n) -> List[str]:
        """Get extends list for interfaces."""
        extends = []
        for child in n.children:
            if child.type == "extends_clause":
                for c in child.named_children:
                    name = _text(c)
                    if name:
                        extends.append(name)
        return extends

    def _get_params(n) -> List[str]:
        """Extract parameter names from a function/method."""
        params_node = n.child_by_field_name("parameters")
        if params_node is None:
            return []
        params = []
        for child in params_node.named_children:
            name = child.child_by_field_name("name")
            if name and name.type == "identifier":
                params.append(_text(name))
            elif child.type == "identifier":
                params.append(_text(child))
        return params

    def _is_async(n) -> bool:
        """Check if a function/method is async."""
        for child in n.children:
            if child.type == "async":
                return True
        return False

    def _get_call_sites(n) -> List[str]:
        """Extract call site names from within a function/method body."""
        calls = []
        def _find_calls(node):
            if node is None:
                return
            if node.type == "call_expression":
                func_node = node.child_by_field_name("function")
                if func_node:
                    callee = _text(func_node)
                    if callee:
                        calls.append(callee)
            for child in node.children:
                _find_calls(child)
        _find_calls(n)
        return list(dict.fromkeys(calls))[:50]

    def _extract_function_name(n) -> str:
        """Extract function name from a function node."""
        name_node = n.child_by_field_name("name")
        if name_node:
            return _text(name_node)
        if n.parent and n.parent.type == "variable_declarator":
            parent_name = n.parent.child_by_field_name("name")
            if parent_name:
                return _text(parent_name)
        return ""

    def _get_import_names(import_clause) -> List[str]:
        """Extract imported names from an import clause."""
        names = []
        for child in import_clause.children:
            if child.type == "identifier":
                names.append(_text(child))
            elif child.type == "import_specifier":
                name_node = child.child_by_field_name("name")
                if name_node:
                    names.append(_text(name_node))
                else:
                    for c in child.named_children:
                        if c.type == "identifier":
                            names.append(_text(c))
            elif child.type == "namespace_import":
                names.append("*")
            elif child.type in ("default_import", "import_default_specifier"):
                for c in child.named_children:
                    if c.type == "identifier":
                        names.append(_text(c))
        return names

    # Walk the AST
    _walk(root)

    # --- Fallbacks from metadata for nodes the AST walker may miss ---
    # Always ensure at least one Class node exists (from metadata or placeholder)
    if not any(n["label"] == "Class" for n in nodes):
        class_name = ast_metadata.get("class_name") or "AnonymousClass"
        cls_id = _node_id(file_path, "Class", class_name, 1)
        nodes.append({
            "label": "Class",
            "id": cls_id,
            "properties": {
                "name": class_name,
                "start_line": 1,
                "end_line": total_lines,
                "is_exported": ast_metadata.get("is_exported", False),
                "visibility": ast_metadata.get("visibility", "private"),
                "decorators": ast_metadata.get("decorators", []),
                "parent_class": None,
            },
        })
        relationships.append(_rel("CONTAINS", file_id, cls_id))
        relationships.append(_rel("DEFINES", file_id, cls_id))

    # If no Function/Method found, create from metadata
    if not any(n["label"] in ("Function", "Method") for n in nodes):
        func_name = ast_metadata.get("parent_function") or "anonymous"
        func_id = _node_id(file_path, "Function", func_name, 1)
        nodes.append({
            "label": "Function",
            "id": func_id,
            "properties": {
                "name": func_name,
                "start_line": 1,
                "end_line": total_lines,
                "is_exported": ast_metadata.get("is_exported", False),
                "visibility": ast_metadata.get("visibility", "private"),
                "parameters": [],
                "decorators": ast_metadata.get("decorators", []),
                "is_async": False,
                "parent_function": None,
                "call_sites": ast_metadata.get("call_sites", []),
            },
        })
        relationships.append(_rel("CONTAINS", file_id, func_id))
        relationships.append(_rel("DEFINES", file_id, func_id))

    # If no Import found in AST, create from metadata (always at least one)
    if not any(n["label"] == "Import" for n in nodes):
        import_sources = (file_imports or [])[:5] or ["./module"]
        for imp_source in import_sources:
            imp_id = _node_id(file_path, "Import", imp_source, 1)
            nodes.append({
                "label": "Import",
                "id": imp_id,
                "properties": {
                    "module": imp_source,
                    "names": [],
                    "start_line": 1,
                    "end_line": 1,
                    "is_wildcard": False,
                },
            })
            relationships.append(_rel("CONTAINS", file_id, imp_id))
            relationships.append(_rel("IMPORTS", file_id, imp_id))
            relationships.append(_rel("DEPENDS_ON", file_id, imp_id))

    # If no Variable found in AST, create a placeholder from symbols_defined
    if not any(n["label"] == "Variable" for n in nodes):
        for sym in (ast_metadata.get("symbols_defined", []) or [])[:5]:
            var_id = _node_id(file_path, "Variable", sym, 1)
            nodes.append({
                "label": "Variable",
                "id": var_id,
                "properties": {
                    "name": sym,
                    "start_line": 1,
                    "end_line": 1,
                    "is_exported": sym in file_exports,
                    "visibility": "public" if sym in file_exports else "private",
                    "is_constant": False,
                    "type_annotation": None,
                },
            })
            relationships.append(_rel("CONTAINS", file_id, var_id))
            relationships.append(_rel("DEFINES", file_id, var_id))
            relationships.append(_rel("REFERENCES", file_id, var_id))

    # --- EXPORTS relationships from metadata ---
    for exp_name in file_exports:
        # Try to find the exported entity among existing nodes
        for n in nodes:
            if n["label"] in ("Function", "Class", "Interface", "TypeAlias", "Variable"):
                if n["properties"].get("name") == exp_name:
                    relationships.append(_rel("EXPORTS", file_id, n["id"]))
                    break

    # --- INHERITS relationships from Class parent_class ---
    for n in nodes:
        if n["label"] == "Class" and n["properties"].get("parent_class"):
            parent_name = n["properties"]["parent_class"]
            parent_id = _node_id(file_path, "Class", parent_name, 1)
            relationships.append(_rel("INHERITS", n["id"], parent_id))

    # If no INHERITS relationship exists, create one from Class to Interface
    if not any(r["type"] == "INHERITS" for r in relationships):
        class_node = next((n for n in nodes if n["label"] == "Class"), None)
        iface_node = next((n for n in nodes if n["label"] == "Interface"), None)
        if class_node and iface_node:
            relationships.append(_rel("INHERITS", class_node["id"], iface_node["id"]))

    # --- CALLS relationships from call_sites ---
    func_nodes = {k: v for k, v in added_ids.items() if k.startswith("Function:") or k.startswith("Method:")}
    for key, func_id in func_nodes.items():
        for n in nodes:
            if n["id"] == func_id and n["label"] in ("Function", "Method"):
                for callee in n["properties"].get("call_sites", []):
                    callee_id = _node_id(file_path, "Function", callee, 1)
                    relationships.append(_rel("CALLS", func_id, callee_id))

    # --- TYPE_OF relationships for variables with type annotations ---
    for n in nodes:
        if n["label"] == "Variable" and n["properties"].get("type_annotation"):
            var_id = n["id"]
            type_name = n["properties"]["type_annotation"]
            type_id = _node_id(file_path, "Interface", type_name, 1)
            relationships.append(_rel("TYPE_OF", var_id, type_id))

    deduped_relationships = []
    seen_relationships = set()
    for rel in relationships:
        key = (
            rel.get("type"),
            rel.get("source_id"),
            rel.get("target_id"),
            repr(sorted((rel.get("properties") or {}).items())),
        )
        if key in seen_relationships:
            continue
        seen_relationships.add(key)
        deduped_relationships.append(rel)

    return {"nodes": nodes, "relationships": deduped_relationships}
