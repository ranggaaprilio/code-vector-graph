# Code Vector Graph - Implementation Guide

## Overview

This document provides a step-by-step implementation plan to refine your code embedding service for AI-powered impact analysis.

**Current State**: Semantic search engine (finds similar text)  
**Target State**: Dependency graph engine (traces code relationships)

---

## Phase 0: Critical Bug Fixes (START HERE)

### [ ] 1. Fix Global State Bug in parser.py

**File**: `src/parser.py`  
**Priority**: 🔴 CRITICAL  
**Effort**: 30 minutes  
**Impact**: Prevents data corruption in parallel processing

**Problem**: The global `_LAST_SOURCE_BYTES` variable causes data races.

**Current Code**:
```python
# Line 31 - REMOVE THIS
_LAST_SOURCE_BYTES: Optional[bytes] = None

# Line 155-156 - REMOVE THIS
global _LAST_SOURCE_BYTES
_LAST_SOURCE_BYTES = source_bytes

# Line 168-171 - REMOVE global reference
def extract_function_name(tree, node_start_byte: int, node_end_byte: int) -> Optional[str]:
    global _LAST_SOURCE_BYTES  # REMOVE
    if _LAST_SOURCE_BYTES is None:  # CHANGE
        return None
    src = _LAST_SOURCE_BYTES  # CHANGE
```

**New Code**:
```python
# Remove line 31 entirely (delete the global variable)

# In strip_comments() function - REMOVE lines 155-156:
# global _LAST_SOURCE_BYTES
# _LAST_SOURCE_BYTES = source_bytes

# Update parse_file() to return source_bytes:
def parse_file(file_path: str, grammar_name: str) -> Optional[dict]:
    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except OSError as e:
        _LOGGER.warning("Failed to read %s: %s", file_path, e)
        return None

    try:
        stripped_text, line_map = strip_comments(data, grammar_name)
    except Exception as e:
        _LOGGER.warning("Failed to strip comments for %s: %s", file_path, e)
        return None

    original_line_count = data.count(b"\n") + (0 if data.endswith(b"\n") else 1)
    stripped_line_count = stripped_text.count("\n") + (0 if stripped_text.endswith("\n") else 1)

    return {
        "stripped_text": stripped_text,
        "original_line_count": original_line_count,
        "stripped_line_count": stripped_line_count,
        "line_mapping": line_map,
        "source_bytes": data,  # ADD THIS
        "tree": None,  # We'll add tree in next step
    }

# Update extract_function_name signature:
def extract_function_name(
    tree, 
    node_start_byte: int, 
    node_end_byte: int, 
    source_bytes: bytes  # ADD THIS PARAMETER
) -> Optional[str]:
    """Extract function name with explicit source bytes."""
    src = source_bytes  # Use parameter instead of global
    root = tree.root_node
    name: Optional[str] = None

    FUNCTION_NODE_TYPES = {
        "function_declaration",
        "function",
        "method_definition",
        "arrow_function",  # ADD
        "async_function_declaration",  # ADD
        "generator_function",  # ADD
    }

    best_candidate = None

    def _enclosing(n) -> bool:
        return n.start_byte <= node_start_byte and n.end_byte >= node_end_byte

    def _walk(n):
        nonlocal best_candidate
        if _enclosing(n) and n.type in FUNCTION_NODE_TYPES:
            for c in n.named_children:
                if c.type in ("identifier", "name", "PropertyName", "property_identifier"):
                    try:
                        text = src[c.start_byte:c.end_byte].decode("utf-8", errors="replace")
                    except Exception:
                        text = None
                    if text:
                        best_candidate = text
        for ch in n.children:
            _walk(ch)

    _walk(root)
    if best_candidate:
        name = best_candidate
    return name
```

**Verification**: Run tests to ensure function name extraction still works.

---

### [ ] 2. Fix Bare Exception Handling

**File**: `src/parser.py`  
**Lines**: 222-224  
**Priority**: 🟠 HIGH

**Current**:
```python
except Exception as e:
    _LOGGER.warning("Failed to strip comments for %s: %s", file_path, e)
    return None
```

**Fix**:
```python
except (ValueError, RuntimeError, OSError, UnicodeDecodeError) as e:
    _LOGGER.warning("Failed to strip comments for %s: %s", file_path, e)
    return None
```

---

## Phase 1: Core Metadata Extraction

### [ ] 3. Add AST Metadata Extraction Function

**File**: `src/parser.py`  
**Priority**: 🔴 CRITICAL  
**Effort**: 2-3 hours

Add this function after `extract_function_name()`:

```python
def extract_ast_metadata(tree, source_bytes: bytes) -> dict:
    """
    Extract rich AST metadata for impact analysis.
    
    Returns metadata including:
    - imports: List of imported modules
    - exports: List of exported symbols
    - call_sites: Functions/methods called in this code
    - symbols_defined: Functions, classes, variables defined
    - class_name: Parent class if inside a class
    - node_type: Type of code entity (function, class, etc.)
    - is_exported: Whether symbols are exported
    - visibility: public/private/protected
    - decorators: List of decorators/annotations
    """
    root = tree.root_node
    
    metadata = {
        "imports": [],
        "exports": [],
        "call_sites": [],
        "symbols_defined": [],
        "class_name": None,
        "node_type": None,
        "is_exported": False,
        "visibility": "unknown",
        "decorators": [],
        "parent_function": None,
    }
    
    # Node types we care about
    FUNCTION_NODE_TYPES = {
        "function_declaration",
        "function",
        "method_definition",
        "arrow_function",
        "async_function_declaration",
        "generator_function",
        "async_arrow_function",
    }
    
    CLASS_NODE_TYPES = {
        "class_declaration",
        "class_expression",
    }
    
    def get_node_text(node) -> str:
        """Safely extract text from a node."""
        try:
            return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        except Exception:
            return ""
    
    def extract_decorators(node) -> list:
        """Extract decorators from a node."""
        decorators = []
        # Look for decorator nodes (TypeScript/JavaScript)
        for child in node.children:
            if child.type == "decorator":
                dec_text = get_node_text(child)
                if dec_text:
                    decorators.append(dec_text)
        return decorators
    
    def walk_node(node, in_class=None, in_function=None, is_exported=False):
        """Recursively walk AST and collect metadata."""
        
        # Handle export statements
        if node.type == "export_statement":
            # Mark exported and process children
            for child in node.named_children:
                walk_node(child, in_class=in_class, in_function=in_function, is_exported=True)
            return
        
        # Handle export declarations
        if node.type in ("export_specifier", "export_clause"):
            # Extract export names
            for child in node.named_children:
                if child.type in ("identifier", "property_identifier"):
                    export_name = get_node_text(child)
                    if export_name:
                        metadata["exports"].append(export_name)
                        metadata["symbols_defined"].append(export_name)
            return
        
        # Handle class declarations
        if node.type in CLASS_NODE_TYPES:
            class_name = None
            for child in node.named_children:
                if child.type == "identifier":
                    class_name = get_node_text(child)
                    break
            
            if class_name:
                metadata["symbols_defined"].append(class_name)
                if is_exported:
                    metadata["exports"].append(class_name)
                    metadata["is_exported"] = True
                
                if not metadata["node_type"]:
                    metadata["node_type"] = "class"
                    metadata["class_name"] = class_name
                
                # Extract class decorators
                metadata["decorators"].extend(extract_decorators(node))
            
            # Walk class body for methods
            for child in node.children:
                if child.type == "class_body":
                    for member in child.children:
                        walk_node(member, in_class=class_name, in_function=in_function, is_exported=is_exported)
            return
        
        # Handle function declarations
        if node.type in FUNCTION_NODE_TYPES:
            func_name = None
            for child in node.named_children:
                if child.type in ("identifier", "property_identifier"):
                    func_name = get_node_text(child)
                    break
            
            if func_name:
                metadata["symbols_defined"].append(func_name)
                if is_exported:
                    metadata["exports"].append(func_name)
                    metadata["is_exported"] = True
                
                if not metadata["node_type"]:
                    metadata["node_type"] = "function"
                    if in_class:
                        metadata["class_name"] = in_class
                    metadata["parent_function"] = in_function
                
                # Extract function decorators
                metadata["decorators"].extend(extract_decorators(node))
            
            # Walk function body for nested calls
            for child in node.children:
                if child.type in ("statement_block", "function_body"):
                    for stmt in child.children:
                        walk_node(stmt, in_class=in_class, in_function=func_name or in_function, is_exported=False)
            return
        
        # Handle call expressions
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func:
                call_name = None
                if func.type == "identifier":
                    call_name = get_node_text(func)
                elif func.type == "member_expression":
                    obj = func.child_by_field_name("object")
                    prop = func.child_by_field_name("property")
                    if obj and prop:
                        obj_text = get_node_text(obj)
                        prop_text = get_node_text(prop)
                        call_name = f"{obj_text}.{prop_text}"
                    elif prop:
                        call_name = get_node_text(prop)
                
                if call_name:
                    metadata["call_sites"].append(call_name)
        
        # Handle import statements
        if node.type in ("import_statement", "import_clause"):
            # Get import source
            source = node.child_by_field_name("source")
            if source and source.type == "string":
                import_path = get_node_text(source).strip("'\"`")
                metadata["imports"].append(import_path)
            
            # Get imported names
            for child in node.named_children:
                if child.type in ("import_specifier", "identifier"):
                    imported_name = get_node_text(child)
                    if imported_name and imported_name not in metadata["imports"]:
                        metadata["imports"].append(imported_name)
        
        # Handle variable declarations (for exported variables)
        if node.type == "variable_declaration":
            for child in node.named_children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    if name_node and name_node.type == "identifier":
                        var_name = get_node_text(name_node)
                        if var_name:
                            metadata["symbols_defined"].append(var_name)
                            if is_exported:
                                metadata["exports"].append(var_name)
        
        # Recurse for other node types
        for child in node.children:
            if child.type not in ("class_body", "statement_block", "function_body"):
                walk_node(child, in_class=in_class, in_function=in_function, is_exported=is_exported)
    
    # Start walking from root
    walk_node(root)
    
    # Post-processing
    # Remove duplicates while preserving order
    metadata["imports"] = list(dict.fromkeys(metadata["imports"]))
    metadata["exports"] = list(dict.fromkeys(metadata["exports"]))
    metadata["call_sites"] = list(dict.fromkeys(metadata["call_sites"]))
    metadata["symbols_defined"] = list(dict.fromkeys(metadata["symbols_defined"]))
    metadata["decorators"] = list(dict.fromkeys(metadata["decorators"]))
    
    # Limit list sizes to prevent payload bloat (Qdrant performance)
    metadata["imports"] = metadata["imports"][:50]
    metadata["exports"] = metadata["exports"][:50]
    metadata["call_sites"] = metadata["call_sites"][:100]
    metadata["symbols_defined"] = metadata["symbols_defined"][:50]
    metadata["decorators"] = metadata["decorators"][:20]
    
    return metadata
```

---

### [ ] 4. Update parse_file to Return AST Tree

**File**: `src/parser.py`  
**Priority**: 🔴 CRITICAL

Update `parse_file()` to return the tree for metadata extraction:

```python
def parse_file(file_path: str, grammar_name: str) -> Optional[dict]:
    """
    Parse a file and return a dict with stripped text, line mappings, and AST tree.
    
    On encoding or parse errors, return None.
    """
    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except OSError as e:
        _LOGGER.warning("Failed to read %s: %s", file_path, e)
        return None

    try:
        parser = get_parser(grammar_name)
        tree = parser.parse(data)  # Parse once
        stripped_text, line_map = strip_comments_with_tree(data, grammar_name, tree)
    except (ValueError, RuntimeError, OSError, UnicodeDecodeError) as e:
        _LOGGER.warning("Failed to parse %s: %s", file_path, e)
        return None

    original_line_count = data.count(b"\n") + (0 if data.endswith(b"\n") else 1)
    stripped_line_count = stripped_text.count("\n") + (0 if stripped_text.endswith("\n") else 1)

    return {
        "stripped_text": stripped_text,
        "original_line_count": original_line_count,
        "stripped_line_count": stripped_line_count,
        "line_mapping": line_map,
        "source_bytes": data,
        "tree": tree,  # Include tree for metadata extraction
    }


def strip_comments_with_tree(source_bytes: bytes, grammar_name: str, tree) -> Tuple[str, Dict[int, int]]:
    """
    Strip comments using an existing parse tree.
    
    This avoids re-parsing the file.
    """
    root = tree.root_node

    # Collect comment ranges
    comment_ranges: list = []
    _collect_comment_ranges(root, comment_ranges)
    comment_ranges.sort()

    # Merge overlapping ranges
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
    
    # Build stripped text
    non_comment_parts: list = []
    cur = 0
    for (start, end) in merged:
        if cur < start:
            non_comment_parts.append(source_bytes[cur:start])
        cur = max(cur, end)
    if cur < len(source_bytes):
        non_comment_parts.append(source_bytes[cur:])
    
    stripped_bytes = b"".join(non_comment_parts)
    stripped_text = stripped_bytes.decode("utf-8", errors="replace")

    # Build line map
    line_map: Dict[int, int] = {}
    line_num = 1
    for i in range(0, len(source_bytes)):
        line_map[i] = line_num
        if source_bytes[i] == 0x0A:  # \n
            line_num += 1

    return stripped_text, line_map
```

---

## Phase 2: Enhanced Chunking

### [ ] 5. Update Chunker with Impact Metadata

**File**: `src/chunker.py`  
**Priority**: 🟠 HIGH  
**Effort**: 1-2 hours

Add new parameters to `chunk_text()`:

```python
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
    # NEW: Impact analysis parameters
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
    """
    Split text into token-aware chunks with impact analysis metadata.
    """
    tokenizer = load_tokenizer()
    if not text:
        return []

    lines = text.splitlines()
    if not lines:
        return []

    # Calculate nesting depth
    nesting_depth = 0
    for line in lines:
        open_count = line.count('{') + line.count('(') + line.count('[')
        close_count = line.count('}') + line.count(')') + line.count(']')
        line_depth = open_count - close_count
        if line_depth > nesting_depth:
            nesting_depth = line_depth

    line_token_counts = _line_token_counts(lines, tokenizer)

    start_idx = 0
    end_idx = 0
    current_tokens = 0
    chunks: List[Dict] = []

    while end_idx < len(lines):
        if current_tokens + line_token_counts[end_idx] <= chunk_size:
            current_tokens += line_token_counts[end_idx]
            end_idx += 1
            continue

        # Handle single line overflow
        if end_idx == start_idx:
            chunk_lines = lines[start_idx : end_idx + 1]
            chunk_text_segment = "\n".join(chunk_lines)
            token_count = count_tokens(chunk_text_segment, tokenizer)
            
            chunks.append({
                "text": chunk_text_segment,
                "metadata": {
                    # Existing fields
                    "file_path": file_path,
                    "language": language,
                    "start_line": start_line + start_idx,
                    "end_line": start_line + end_idx,
                    "chunk_index": len(chunks) + 1,
                    "function_name": function_name,
                    "total_chunks": 0,
                    
                    # NEW: Impact analysis metadata
                    "node_type": node_type,
                    "class_name": class_name,
                    "parent_function": parent_function,
                    "imports": imports or [],
                    "exports": exports or [],
                    "symbols_defined": symbols_defined or [],
                    "call_sites": call_sites or [],
                    "is_exported": is_exported,
                    "visibility": visibility,
                    "nesting_depth": nesting_depth,
                    "token_count": token_count,
                    "decorators": decorators or [],
                    "file_hash": file_hash,
                },
            })
            end_idx += 1
            start_idx = end_idx
            current_tokens = 0
            continue

        # Normal case: finalize chunk
        chunk_lines = lines[start_idx:end_idx]
        chunk_text_segment = "\n".join(chunk_lines)
        token_count = count_tokens(chunk_text_segment, tokenizer)
        
        chunks.append({
            "text": chunk_text_segment,
            "metadata": {
                # Existing fields
                "file_path": file_path,
                "language": language,
                "start_line": start_line + start_idx,
                "end_line": start_line + end_idx - 1,
                "chunk_index": len(chunks) + 1,
                "function_name": function_name,
                "total_chunks": 0,
                
                # NEW: Impact analysis metadata
                "node_type": node_type,
                "class_name": class_name,
                "parent_function": parent_function,
                "imports": imports or [],
                "exports": exports or [],
                "symbols_defined": symbols_defined or [],
                "call_sites": call_sites or [],
                "is_exported": is_exported,
                "visibility": visibility,
                "nesting_depth": nesting_depth,
                "token_count": token_count,
                "decorators": decorators or [],
                "file_hash": file_hash,
            },
        })

        # Compute overlap
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

    # Final chunk
    if end_idx > start_idx:
        chunk_lines = lines[start_idx:end_idx]
        chunk_text_segment = "\n".join(chunk_lines)
        token_count = count_tokens(chunk_text_segment, tokenizer)
        
        chunks.append({
            "text": chunk_text_segment,
            "metadata": {
                # Existing fields
                "file_path": file_path,
                "language": language,
                "start_line": start_line + start_idx,
                "end_line": start_line + end_idx - 1,
                "chunk_index": len(chunks) + 1,
                "function_name": function_name,
                "total_chunks": 0,
                
                # NEW: Impact analysis metadata
                "node_type": node_type,
                "class_name": class_name,
                "parent_function": parent_function,
                "imports": imports or [],
                "exports": exports or [],
                "symbols_defined": symbols_defined or [],
                "call_sites": call_sites or [],
                "is_exported": is_exported,
                "visibility": visibility,
                "nesting_depth": nesting_depth,
                "token_count": token_count,
                "decorators": decorators or [],
                "file_hash": file_hash,
            },
        })

    if not chunks:
        return []

    # Update total_chunks
    total = len(chunks)
    for idx in range(len(chunks)):
        chunks[idx]["metadata"]["total_chunks"] = total
        chunks[idx]["metadata"]["chunk_index"] = idx + 1

    return chunks
```

---

## Phase 3: Enhanced Storage

### [ ] 6. Add File Hashing to Scanner

**File**: `src/scanner.py`  
**Priority**: 🟠 HIGH  
**Effort**: 30 minutes

```python
import hashlib

def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file contents for change detection."""
    try:
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except (OSError, IOError):
        return ""


def discover_files(repo_path: str) -> list[dict]:
    """
    Discover JS/TS/TSX files in repository with content hashing.
    """
    results = []
    repo = Path(repo_path)

    for root, dirs, files in os.walk(repo):
        # Filter out directories to skip
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

            # Compute file hash for incremental updates
            file_hash = compute_file_hash(file_path)

            info = SUPPORTED_EXTENSIONS[ext]
            results.append({
                "path": str(file_path),
                "extension": ext,
                "language": info["language"],
                "grammar": info["grammar"],
                "file_hash": file_hash,  # NEW: For change detection
            })

    # Sort by file path for consistent ordering
    results.sort(key=lambda x: x["path"])
    return results
```

---

### [ ] 7. Add Payload Indexes to Qdrant

**File**: `src/store.py`  
**Priority**: 🔴 CRITICAL  
**Effort**: 1 hour

```python
from qdrant_client.models import (
    Distance, 
    PointStruct, 
    VectorParams,
    PayloadSchemaType,
)

class VectorStore:
    """Qdrant vector store with deterministic UUID5 IDs and impact analysis indexes."""

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        qdrant_url: str = DEFAULT_QDRANT_URL,
        embedding_dimensions: int = EMBEDDING_DIMENSIONS,
    ):
        self.collection_name = collection_name
        self.embedding_dimensions = embedding_dimensions

        if qdrant_url == ":memory:":
            self.client = QdrantClient(":memory:")
        else:
            self.client = QdrantClient(url=qdrant_url)

        logger.debug(f"Initialized VectorStore for collection '{collection_name}' at {qdrant_url}")

    def check_health(self) -> bool:
        """Check if Qdrant is reachable."""
        try:
            self.client.get_collections()
            logger.debug("Qdrant health check: OK")
            return True
        except Exception as e:
            logger.error(f"Qdrant health check failed: {e}")
            return False

    def create_collection(self) -> None:
        """Create collection with payload indexes for impact analysis."""
        try:
            if self.client.collection_exists(self.collection_name):
                logger.info(f"Collection '{self.collection_name}' already exists")
                self._ensure_indexes()
                return

            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_dimensions,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Created collection '{self.collection_name}' with {self.embedding_dimensions} dimensions (COSINE)")
            
            # Create payload indexes for efficient filtering
            self._ensure_indexes()
            
        except Exception as e:
            logger.error(f"Failed to create collection: {e}")
            raise

    def _ensure_indexes(self) -> None:
        """Create payload indexes for impact analysis queries."""
        indexes = [
            ("file_path", PayloadSchemaType.KEYWORD),
            ("language", PayloadSchemaType.KEYWORD),
            ("node_type", PayloadSchemaType.KEYWORD),
            ("class_name", PayloadSchemaType.KEYWORD),
            ("function_name", PayloadSchemaType.KEYWORD),
            ("imports", PayloadSchemaType.KEYWORD),
            ("exports", PayloadSchemaType.KEYWORD),
            ("call_sites", PayloadSchemaType.KEYWORD),
            ("is_exported", PayloadSchemaType.BOOL),
            ("visibility", PayloadSchemaType.KEYWORD),
            ("file_hash", PayloadSchemaType.KEYWORD),
        ]
        
        for field_name, field_type in indexes:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=field_type,
                )
                logger.debug(f"Created index on {field_name}")
            except Exception as e:
                # Index might already exist
                logger.debug(f"Index on {field_name}: {e}")

    def _generate_deterministic_id(self, file_path: str, chunk_index: int, file_hash: str = "") -> str:
        """Generate deterministic UUID5 ID from file path, chunk index, and hash."""
        namespace = uuid.NAMESPACE_URL
        name = f"{file_path}:{chunk_index}:{file_hash}"
        return str(uuid.uuid5(namespace, name))

    def _chunk_to_point(self, chunk: dict[str, Any]) -> PointStruct:
        """Convert chunk with enhanced metadata to PointStruct."""
        file_path = chunk["file_path"]
        chunk_index = chunk["chunk_index"]
        file_hash = chunk.get("file_hash", "")

        point_id = self._generate_deterministic_id(file_path, chunk_index, file_hash)

        payload = {
            # Existing fields
            "file_path": file_path,
            "language": chunk["language"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "chunk_index": chunk_index,
            "function_name": chunk.get("function_name"),
            "total_chunks": chunk["total_chunks"],
            "text_content": chunk.get("text_content", chunk.get("text", "")),
            
            # NEW: Impact analysis metadata
            "node_type": chunk.get("node_type", "unknown"),
            "class_name": chunk.get("class_name"),
            "parent_function": chunk.get("parent_function"),
            "imports": chunk.get("imports", []),
            "exports": chunk.get("exports", []),
            "symbols_defined": chunk.get("symbols_defined", []),
            "call_sites": chunk.get("call_sites", []),
            "is_exported": chunk.get("is_exported", False),
            "visibility": chunk.get("visibility", "unknown"),
            "nesting_depth": chunk.get("nesting_depth", 0),
            "token_count": chunk.get("token_count", 0),
            "decorators": chunk.get("decorators", []),
            "file_hash": file_hash,
        }

        return PointStruct(
            id=point_id,
            vector=chunk["embedding"],
            payload=payload,
        )

    def upsert_chunks(self, chunks: list[dict[str, Any]], batch_size: int = 100) -> list[str]:
        """Upsert chunks to Qdrant in batches with deterministic IDs."""
        if not chunks:
            logger.info("No chunks to upsert")
            return []

        points = [self._chunk_to_point(chunk) for chunk in chunks]
        point_ids = [point.id for point in points]

        total_batches = (len(points) + batch_size - 1) // batch_size

        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(points))
            batch = points[start_idx:end_idx]

            logger.info(f"Upserting batch {batch_idx + 1}/{total_batches} ({len(batch)} points)")

            self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
            )

        logger.info(f"Successfully upserted {len(points)} chunks")
        return point_ids

    def get_point(self, point_id: str) -> dict[str, Any] | None:
        """Retrieve a point by ID for verification."""
        try:
            points = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
            )
            if points:
                point = points[0]
                return {
                    "id": point.id,
                    "vector": point.vector,
                    "payload": point.payload,
                }
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve point {point_id}: {e}")
            return None
```

---

## Phase 4: Updated Pipeline

### [ ] 8. Update Main Pipeline

**File**: `main.py`  
**Priority**: 🟠 HIGH  
**Effort**: 1 hour

Update the pipeline to pass AST metadata through:

```python
def run_pipeline(args) -> dict:
    """Run the full embedding pipeline with impact analysis metadata."""
    stats = {
        "files_found": 0,
        "files_parsed": 0,
        "files_failed": 0,
        "total_chunks": 0,
        "chunks_embedded": 0,
        "chunks_stored": 0,
    }

    logger.info(f"Starting pipeline for repository: {args.repo_path}")

    # Step 1: Discover files
    logger.info("Discovering files...")
    files = discover_files(args.repo_path)
    stats["files_found"] = len(files)
    logger.info(f"Found {len(files)} supported files")

    if not files:
        logger.warning("No files found to process")
        return stats

    # Step 2: Initialize components
    embedder = CodeEmbedder(model=args.model, base_url=args.ollama_url)
    store = VectorStore(
        collection_name=args.collection_name,
        qdrant_url=args.qdrant_url,
    )

    # Health checks
    if not args.dry_run:
        check_ollama_health(embedder)
        check_qdrant_health(store)
        store.create_collection()
    else:
        logger.info("Dry-run mode: skipping health checks for external services")

    # Step 3: Parse and chunk files
    all_chunks = []

    for file_info in files:
        file_path = file_info["path"]
        grammar = file_info["grammar"]
        language = file_info["language"]
        file_hash = file_info.get("file_hash", "")

        logger.debug(f"Processing file: {file_path}")

        # Parse file
        parsed = parse_file(file_path, grammar)
        if parsed is None:
            logger.warning(f"Failed to parse file: {file_path}")
            stats["files_failed"] += 1
            continue

        stats["files_parsed"] += 1

        # NEW: Extract AST metadata
        ast_metadata = extract_ast_metadata(parsed["tree"], parsed["source_bytes"])
        logger.debug(f"Extracted metadata for {file_path}: {ast_metadata['node_type']} with {len(ast_metadata['imports'])} imports")

        # Chunk the parsed text with AST metadata
        chunks = chunk_text(
            text=parsed["stripped_text"],
            start_line=1,
            end_line=parsed["stripped_line_count"],
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            file_path=file_path,
            language=language,
            file_hash=file_hash,  # Pass file hash for incremental updates
            # Pass AST metadata
            node_type=ast_metadata.get("node_type"),
            class_name=ast_metadata.get("class_name"),
            parent_function=ast_metadata.get("parent_function"),
            imports=ast_metadata.get("imports"),
            exports=ast_metadata.get("exports"),
            symbols_defined=ast_metadata.get("symbols_defined"),
            call_sites=ast_metadata.get("call_sites"),
            is_exported=ast_metadata.get("is_exported", False),
            visibility=ast_metadata.get("visibility", "unknown"),
            decorators=ast_metadata.get("decorators"),
        )

        # Flatten metadata and add text_content field for storage
        for chunk in chunks:
            metadata = chunk.pop("metadata", {})
            chunk.update(metadata)
            chunk["text_content"] = chunk["text"]

        all_chunks.extend(chunks)
        logger.debug(f"Created {len(chunks)} chunks from {file_path}")

    stats["total_chunks"] = len(all_chunks)
    logger.info(f"Created {len(all_chunks)} total chunks from {stats['files_parsed']} files")

    # Step 4: Dry-run mode - stop here
    if args.dry_run:
        avg_chunk_size = 0
        if all_chunks:
            total_size = sum(len(chunk["text"]) for chunk in all_chunks)
            avg_chunk_size = total_size // len(all_chunks)

        print("\n" + "=" * 50)
        print("DRY RUN COMPLETE")
        print("=" * 50)
        print(f"Files found:    {stats['files_found']}")
        print(f"Files parsed:   {stats['files_parsed']}")
        print(f"Files failed:   {stats['files_failed']}")
        print(f"Total chunks:   {stats['total_chunks']}")
        print(f"Avg chunk size: {avg_chunk_size} chars")
        print("=" * 50)
        print("No embeddings were generated or stored.")
        print("Run without --dry-run to perform full embedding.")
        print("=" * 50)

        return stats

    # Step 5: Embed chunks
    if all_chunks:
        logger.info(f"Embedding {len(all_chunks)} chunks (batch size: {args.batch_size})...")
        embedded_chunks = embedder.embed_chunks(all_chunks, batch_size=args.batch_size)
        stats["chunks_embedded"] = len(embedded_chunks)
        logger.info(f"Successfully embedded {len(embedded_chunks)} chunks")
    else:
        embedded_chunks = []
        logger.warning("No chunks to embed")

    # Step 6: Store chunks in Qdrant
    if embedded_chunks:
        logger.info(f"Storing {len(embedded_chunks)} chunks in Qdrant...")
        point_ids = store.upsert_chunks(embedded_chunks)
        stats["chunks_stored"] = len(point_ids)
        logger.info(f"Successfully stored {len(point_ids)} chunks")
    else:
        logger.warning("No chunks to store")

    # Final summary
    logger.info("Pipeline completed successfully")
    print(f"\nPipeline Summary:")
    print(f"  Files processed: {stats['files_parsed']}/{stats['files_found']}")
    print(f"  Chunks embedded: {stats['chunks_embedded']}")
    print(f"  Chunks stored:   {stats['chunks_stored']}")

    return stats
```

---

## Phase 5: Query Examples

### [ ] 9. Example Impact Analysis Queries

Once implemented, you can perform these queries:

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

# Example 1: Find all code that imports a specific module
def find_importers(module_name: str, client, collection_name="code_chunks"):
    """Find all chunks that import a specific module."""
    results = client.search(
        collection_name=collection_name,
        query_vector=[0.0] * 768,  # Dummy vector for filtering only
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="imports",
                    match=MatchAny(any=[module_name])
                )
            ]
        ),
        limit=100,
        with_payload=True,
    )
    return results

# Example 2: Find all callers of a function
def find_callers(function_name: str, client, collection_name="code_chunks"):
    """Find all chunks that call a specific function."""
    results = client.search(
        collection_name=collection_name,
        query_vector=[0.0] * 768,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="call_sites",
                    match=MatchAny(any=[function_name])
                )
            ]
        ),
        limit=100,
        with_payload=True,
    )
    return results

# Example 3: Find exported functions in a class
def find_class_methods(class_name: str, client, collection_name="code_chunks"):
    """Find all exported methods of a class."""
    results = client.search(
        collection_name=collection_name,
        query_vector=[0.0] * 768,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="class_name",
                    match=MatchValue(value=class_name)
                ),
                FieldCondition(
                    key="is_exported",
                    match=MatchValue(value=True)
                ),
            ]
        ),
        limit=100,
        with_payload=True,
    )
    return results

# Example 4: Find high-risk code (exported + high nesting depth)
def find_high_risk_code(min_depth: int, client, collection_name="code_chunks"):
    """Find exported code with high nesting depth."""
    results = client.scroll(
        collection_name=collection_name,
        scroll_filter=Filter(
            must=[
                FieldCondition(
                    key="is_exported",
                    match=MatchValue(value=True)
                ),
                FieldCondition(
                    key="nesting_depth",
                    range={"gte": min_depth}
                ),
            ]
        ),
        limit=100,
        with_payload=True,
    )
    return results

# Example 5: Combined semantic + structural search
def semantic_filtered_search(query: str, embedder, client, 
                             node_type: str = None, 
                             is_exported: bool = None,
                             collection_name="code_chunks"):
    """Semantic search with structural filtering."""
    # Generate query embedding
    query_vector = embedder.embed_query(query)
    
    # Build filter
    filter_conditions = []
    if node_type:
        filter_conditions.append(
            FieldCondition(key="node_type", match=MatchValue(value=node_type))
        )
    if is_exported is not None:
        filter_conditions.append(
            FieldCondition(key="is_exported", match=MatchValue(value=is_exported))
        )
    
    results = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        query_filter=Filter(must=filter_conditions) if filter_conditions else None,
        limit=10,
        with_payload=True,
    )
    return results
```

---

## Verification Checklist

After implementing each phase, verify:

### Phase 0
- [ ] Tests pass after removing global `_LAST_SOURCE_BYTES`
- [ ] Function name extraction still works
- [ ] Exception handling is more specific

### Phase 1
- [ ] AST metadata is extracted for JS/TS files
- [ ] Imports, exports, and call sites are captured
- [ ] No duplicate symbols in metadata
- [ ] List sizes are bounded (imports ≤50, call_sites ≤100)

### Phase 2
- [ ] Chunk metadata includes all new fields
- [ ] Nesting depth is calculated correctly
- [ ] Token counts are accurate

### Phase 3
- [ ] File hashes are computed
- [ ] Payload indexes are created in Qdrant
- [ ] Points include all metadata fields

### Phase 4
- [ ] Pipeline runs without errors
- [ ] Metadata flows from parser → chunker → store
- [ ] Points are upserted with complete payloads

### Phase 5
- [ ] Can query by imports
- [ ] Can query by call_sites
- [ ] Can filter by node_type
- [ ] Can find class methods

---

## Performance Tips

1. **Batch Processing**: The current implementation processes files sequentially. For large repos, consider using `concurrent.futures` to parse files in parallel.

2. **Memory Management**: For very large files, the AST metadata lists are bounded. If you need more, consider storing relationships in a separate graph database.

3. **Incremental Updates**: Use the `file_hash` field to skip re-processing unchanged files. Compare the hash before parsing.

4. **Index Warming**: After creating payload indexes, Qdrant may need time to build them. For large collections, consider indexing in batches.

---

## Troubleshooting

### Issue: AST metadata is empty
**Solution**: Check that the Tree-sitter grammar is loaded correctly. Verify that `tree` is being passed from `parse_file()`.

### Issue: Imports not captured
**Solution**: The import query may need adjustment for your specific JS/TS patterns. Check the node types in Tree-sitter playground.

### Issue: Indexes not created
**Solution**: Ensure you're calling `_ensure_indexes()` after collection creation. Check Qdrant logs for index creation errors.

### Issue: Payload too large
**Solution**: Reduce the bounds on list fields in `extract_ast_metadata()`:
- imports: 50 → 30
- exports: 50 → 20
- call_sites: 100 → 50
- symbols_defined: 50 → 30

---

## Next Steps

1. Start with **Phase 0** (Critical bug fixes)
2. Then implement **Phase 1** (Core metadata extraction)
3. Test with a small repository
4. Implement **Phase 2** and **Phase 3**
5. Run full pipeline
6. Verify with **Phase 5** queries

Remember: The goal is to transform your system from "find similar text" to "trace code relationships". The metadata you extract enables AI to understand dependency chains, call graphs, and change impact.
