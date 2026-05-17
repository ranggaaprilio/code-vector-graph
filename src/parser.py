"""
Tree-sitter based parser with comment stripping for JS/TS/TSX.

Features:
- Cached per-language parsers
- Strip comments by byte-splicing while preserving line numbers
- Build a line mapping from original offsets to original line numbers
- Extract function names by traversing the AST (best-effort)
- Expose parse helpers: get_parser, strip_comments, parse_file, extract_function_name
"""

import logging
from typing import Dict, Optional, Tuple

from tree_sitter import Language, Parser

# Language bindings (assumed to be installed in the environment)
try:
    import tree_sitter_javascript as tree_js  # type: ignore
except Exception:  # pragma: no cover - fallback for environments without the package
    tree_js = None  # type: ignore
try:
    import tree_sitter_typescript as tree_ts  # type: ignore
except Exception:  # pragma: no cover
    tree_ts = None  # type: ignore

# Public: COMMENT_NODE_TYPES used by tests and internal strips
COMMENT_NODE_TYPES = ("comment", "line_comment", "block_comment")

# Internal caches
_PARSER_CACHE: Dict[str, Parser] = {}

_LOGGER = logging.getLogger(__name__)


def _load_language(grammar_name: str) -> Language:
    # Build a Language object for the requested grammar
    if grammar_name.lower() in ("javascript", "js", "jsx"):
        if tree_js is None:
            raise RuntimeError(
                "tree_sitter_javascript package is not available in this environment"
            )
        return Language(tree_js.language())
    if grammar_name.lower() in ("typescript", "ts"):
        if tree_ts is None:
            raise RuntimeError(
                "tree_sitter_typescript package is not available in this environment"
            )
        return Language(tree_ts.language_typescript())
    if grammar_name.lower() in ("tsx", "typescriptreact"):
        if tree_ts is None:
            raise RuntimeError(
                "tree_sitter_typescript package is not available in this environment"
            )
        return Language(tree_ts.language_tsx())
    raise ValueError(f"Unsupported grammar: {grammar_name}")


def get_parser(grammar_name: str) -> Parser:
    """Return a cached tree-sitter Parser for the given grammar."""
    key = grammar_name.lower()
    if key in _PARSER_CACHE:
        return _PARSER_CACHE[key]
    lang = _load_language(grammar_name)
    parser = Parser(lang)
    _PARSER_CACHE[key] = parser
    return parser


def _collect_comment_ranges(node, ranges: list):
    """Recursively collect all (start_byte, end_byte) ranges for comment nodes."""
    if node.type in COMMENT_NODE_TYPES:
        ranges.append((node.start_byte, node.end_byte))
    for child in node.children:
        _collect_comment_ranges(child, ranges)


def strip_comments(
    source_bytes: bytes, grammar_name: str
) -> Tuple[str, Dict[int, int]]:
    """Strip comments from source_bytes using tree-sitter for the given grammar.

    Returns (stripped_text, line_map).
    line_map maps start-offsets of lines to their 1-based line numbers in the original source.
    """
    parser = get_parser(grammar_name)
    tree = parser.parse(source_bytes)
    root = tree.root_node

    # 1) collect comment ranges
    comment_ranges: list = []
    _collect_comment_ranges(root, comment_ranges)
    comment_ranges.sort()

    # 2) merge overlapping ranges just in case
    merged: list = []
    for r in comment_ranges:
        if not merged:
            merged.append(list(r))
        else:
            last = merged[-1]
            if r[0] <= last[1]:
                last[1] = max(last[1], r[1])
            else:
                merged.append(list(r))
    non_comment_parts: list = []
    cur = 0
    for start, end in merged:
        if cur < start:
            non_comment_parts.append(source_bytes[cur:start])
        cur = max(cur, end)
    if cur < len(source_bytes):
        non_comment_parts.append(source_bytes[cur:])
    stripped_bytes = b"".join(non_comment_parts)
    stripped_text = stripped_bytes.decode("utf-8", errors="replace")

    # 3) build line map for original source
    line_map: Dict[int, int] = {}
    line_num = 1
    for i in range(0, len(source_bytes)):
        line_map[i] = line_num
        if source_bytes[i] == 0x0A:  # \n
            line_num += 1

    return stripped_text, line_map


def strip_comments_with_tree(
    source_bytes: bytes, grammar_name: str, tree
) -> Tuple[str, Dict[int, int]]:
    """Strip comments from source_bytes using a provided pre-parsed tree for the given grammar.

    This mirrors strip_comments but uses the supplied Tree-sitter parse tree instead of
    re-parsing the source bytes.

    Returns (stripped_text, line_map).
    line_map maps start-offsets of lines to their 1-based line numbers in the original source.
    """
    root = tree.root_node

    # 1) collect comment ranges
    comment_ranges: list = []
    _collect_comment_ranges(root, comment_ranges)
    comment_ranges.sort()

    # 2) merge overlapping ranges just in case
    merged: list = []
    for r in comment_ranges:
        if not merged:
            merged.append(list(r))
        else:
            last = merged[-1]
            if r[0] <= last[1]:
                last[1] = max(last[1], r[1])
            else:
                merged.append(list(r))
    non_comment_parts: list = []
    cur = 0
    for start, end in merged:
        if cur < start:
            non_comment_parts.append(source_bytes[cur:start])
        cur = max(cur, end)
    if cur < len(source_bytes):
        non_comment_parts.append(source_bytes[cur:])
    stripped_bytes = b"".join(non_comment_parts)
    stripped_text = stripped_bytes.decode("utf-8", errors="replace")

    # 3) build line map for original source
    line_map: Dict[int, int] = {}
    line_num = 1
    for i in range(0, len(source_bytes)):
        line_map[i] = line_num
        if source_bytes[i] == 0x0A:  # \n
            line_num += 1

    return stripped_text, line_map


def extract_function_name(
    tree, node_start_byte: int, node_end_byte: int, source_bytes: bytes
) -> Optional[str]:
    """Attempt to extract a function name for the function node enclosing [start, end).

    Uses source_bytes to decode identifier text.
    """
    src = source_bytes
    root = tree.root_node
    name: Optional[str] = None

    FUNCTION_NODE_TYPES = {
        "function_declaration",
        "function",
        "method_definition",
    }

    best_candidate = None

    def _enclosing(n) -> bool:
        return n.start_byte <= node_start_byte and n.end_byte >= node_end_byte

    def _walk(n):
        nonlocal best_candidate
        if _enclosing(n) and n.type in FUNCTION_NODE_TYPES:
            # Find a name-like child if possible
            for c in n.named_children:
                if c.type in ("identifier", "name", "PropertyName"):
                    try:
                        text = src[c.start_byte : c.end_byte].decode(
                            "utf-8", errors="replace"
                        )
                    except Exception:
                        text = None
                    if text:
                        best_candidate = text
            # Do not stop; there might be a nested function with a name
        for ch in n.children:
            _walk(ch)

    _walk(root)
    if best_candidate:
        name = best_candidate
    return name


def extract_ast_metadata(tree, source_bytes: bytes) -> dict:
    """Extract lightweight AST metadata from a tree-sitter JS/TS AST.

    Returns a dictionary with the following 11 keys:
    - imports: list[str]
    - exports: list[str]
    - call_sites: list[str]
    - symbols_defined: list[str]
    - class_name: Optional[str]
    - node_type: Optional[str]
    - is_exported: bool
    - visibility: str  # 'public' if exported, otherwise 'private'
    - decorators: list[str]
    - parent_function: Optional[str]  # innermost enclosing function name if any
    """
    # Guard for None trees
    if tree is None:
        return {
            "imports": [],
            "exports": [],
            "call_sites": [],
            "symbols_defined": [],
            "class_name": None,
            "node_type": None,
            "is_exported": False,
            "visibility": "private",
            "decorators": [],
            "parent_function": None,
        }

    root = tree.root_node
    # Result containers
    imports: list[str] = []
    exports: list[str] = []
    call_sites: list[str] = []
    symbols_defined: list[str] = []
    class_name: Optional[str] = None
    node_type: Optional[str] = root.type if root else None
    is_exported: bool = False
    decorators: list[str] = []
    parent_function: Optional[str] = None

    # Runtime helpers
    def _text(n) -> str:
        try:
            return source_bytes[n.start_byte : n.end_byte].decode(
                "utf-8", errors="replace"
            )
        except Exception:
            return ""

    # Recursively collect string literals/text from a subtree
    def _collect_strings(n):
        nonlocal imports
        for c in n.children:
            if c.type == "string":
                t = _text(c).strip().strip('"').strip("'")
                if t:
                    # Treat string literals as potential module imports
                    clean = t.strip().rstrip("")
                    imports.append(clean)
            _collect_strings(c)

    # Walk the tree and populate results
    function_stack: list[str] = []  # innermost function on top

    def _walk(n):
        nonlocal \
            imports, \
            exports, \
            call_sites, \
            symbols_defined, \
            class_name, \
            is_exported, \
            decorators, \
            parent_function

        if n is None:
            return

        t = n.type

        # Detect exports at higher level so descendants can be marked
        if t in ("export_statement", "export_default", "export_clause"):
            is_exported = True

        # Decorators (TS/ESDecorators)
        if t == "decorator":
            # try to extract a simple name for the decorator
            for c in n.named_children:
                if c.type in ("identifier", "name"):
                    decorators.append(_text(c))
                    break
        # Class declarations
        if t == "class_declaration":
            name_node = n.child_by_field_name("name")
            if name_node is not None:
                cname = _text(name_node)
                if cname:
                    class_name = cname
            # Walk into class body
            body = n.child_by_field_name("body")
            if body is not None:
                _walk(body)
            return

        # Function-like nodes
        FUNCTION_NODES = {
            "function_declaration",
            "function",
            "method_definition",
            "arrow_function",
            "async_function_declaration",
            "generator_function",
            "async_arrow_function",
        }
        if t in FUNCTION_NODES:
            fname = extract_function_name(tree, n.start_byte, n.end_byte, source_bytes)
            if fname:
                symbols_defined.append(fname)
                function_stack.append(fname)
                parent_function = function_stack[-1]
            # Walk all children within the function
            for c in n.children:
                _walk(c)
            if fname:
                function_stack.pop()
                parent_function = function_stack[-1] if function_stack else None
            return

        # Call expressions
        if t == "call_expression":
            full = _text(n)
            if "(" in full:
                callee = full.split("(", 1)[0].strip()
                if callee:
                    call_sites.append(callee)
            # still walk children
            for c in n.children:
                _walk(c)
            return

        # Import statements
        if t == "import_statement":
            # collect all string literals under this subtree as imports (module specifiers)
            _collect_strings(n)
            for c in n.children:
                _walk(c)
            return

        # Exports: export_clause / export_specifier could contain names
        if t in ("export_clause", "export_specifier", "export_statement"):
            for c in n.children:
                if c.type == "identifier":
                    nm = _text(c)
                    if nm:
                        exports.append(nm)
                _walk(c)
            return

        # Imports for named imports from export specifier etc
        if t == "import_clause":
            for c in n.children:
                _walk(c)
            return

        # Variable declarations (collect top-level variable names)
        if t == "variable_declaration":
            # descend and take identifiers
            def _collect_ids(x):
                for ch in x.children:
                    if ch.type == "identifier":
                        nm = _text(ch)
                        if nm:
                            symbols_defined.append(nm)
                    _collect_ids(ch)

            _collect_ids(n)
            for c in n.children:
                _walk(c)
            return

        # Class body or other blocks – continue traversal
        for c in n.children:
            _walk(c)

    _walk(root)

    # Post-process: deduplicate and bound sizes
    imports = list(dict.fromkeys([i for i in imports if i]))
    exports = list(dict.fromkeys([e for e in exports if e]))
    call_sites = list(dict.fromkeys([c for c in call_sites if c]))
    symbols_defined = list(dict.fromkeys([s for s in symbols_defined if s]))
    decorators = list(dict.fromkeys([d for d in decorators if d]))

    # Apply bounds
    imports = imports[:50]
    exports = exports[:50]
    call_sites = call_sites[:100]
    symbols_defined = symbols_defined[:50]
    decorators = decorators[:20]

    # Build final result
    metadata = {
        "imports": imports,
        "exports": exports,
        "call_sites": call_sites,
        "symbols_defined": symbols_defined,
        "class_name": class_name,
        "node_type": node_type,
        "is_exported": is_exported,
        "visibility": "public" if is_exported else "private",
        "decorators": decorators,
        "parent_function": parent_function if parent_function is not None else None,
    }
    return metadata


def parse_file(file_path: str, grammar_name: str) -> Optional[dict]:
    """Parse a file and return a dict with stripped text and line mappings.

    On encoding or parse errors, return None.
    """
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        _LOGGER.info("Read %d bytes for %s", len(data), file_path)
    except OSError as e:
        _LOGGER.warning("Failed to read %s: %s", file_path, e)
        return None

    try:
        # Parse the data once to obtain a tree, then strip comments using that tree
        _LOGGER.info("Starting tree-sitter parse for %s", file_path)
        parser = get_parser(grammar_name)
        tree = parser.parse(data)
        _LOGGER.info("Tree-sitter parse complete for %s", file_path)

        _LOGGER.info("Starting comment stripping for %s", file_path)
        stripped_text, line_map = strip_comments_with_tree(data, grammar_name, tree)
        _LOGGER.info("Comment stripping complete for %s", file_path)
    except (ValueError, RuntimeError, OSError, UnicodeDecodeError) as e:
        _LOGGER.warning("Failed to strip comments for %s: %s", file_path, e)
        return None

    original_line_count = data.count(b"\n") + (0 if data.endswith(b"\n") else 1)
    stripped_line_count = stripped_text.count("\n") + (
        0 if stripped_text.endswith("\n") else 1
    )

    return {
        "stripped_text": stripped_text,
        "original_line_count": original_line_count,
        "stripped_line_count": stripped_line_count,
        "line_mapping": line_map,
        "source_bytes": data,
        "tree": tree,
    }
