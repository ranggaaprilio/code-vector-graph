# Code Ontology (Neo4j Graph)

## Node Types

| Label | Description | Key Properties |
|-------|-------------|----------------|
| `File` | Source file | path, language, file_hash, imports, exports |
| `Module` | ES module | name, path, is_package |
| `Class` | Class declaration | name, start_line, end_line, is_exported, visibility, decorators, parent_class |
| `Function` | Function declaration | name, start_line, end_line, is_async, parameters, call_sites, decorators |
| `Method` | Class method | name, parent_class, is_async, parameters, call_sites |
| `Field` | Class field/property | name, parent_class, type_annotation, visibility |
| `Variable` | Variable declaration | name, is_constant, type_annotation, visibility |
| `Import` | Import statement | module, names, is_wildcard |
| `Interface` | TypeScript interface | name, extends |
| `TypeAlias` | TypeScript type alias | name, type_expression |
| `Chunk` | Code chunk (linked to Qdrant) | qdrant_id, file_path, start_line, end_line, token_count |
| `GlossaryEntry` | Manual or comment-derived term explanation | term, kind, summary, source, confidence, symbol_id |
| `WikiPage` | OKF LLM-wiki page documenting a code node | concept_id, path, type, title, summary, overview, tags, resource, source |

## Relationship Types

| Type | Description |
|------|-------------|
| `CONTAINS` | File contains class/function/variable |
| `CALLS` | Function calls another function |
| `IMPORTS` | File/module imports from another |
| `INHERITS` | Class extends another class |
| `EXPORTS` | File exports a symbol |
| `REFERENCES` | Symbol references another |
| `DEFINES` | Module defines a symbol |
| `TYPE_OF` | Type relationship |
| `DEPENDS_ON` | Module dependency |
| `HAS_GLOSSARY` | Symbol has a glossary explanation |
| `DOCUMENTS` | OKF `WikiPage` documents a code node |

