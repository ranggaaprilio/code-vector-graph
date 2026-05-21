# Indexing Your Codebase Into Live Documentation for AI

Most engineering teams have two versions of their documentation.

The first version is the one they wrote: architecture diagrams, onboarding guides, API notes, and a few carefully maintained README files. The second version is the one that actually matters: the source code as it exists today.

The problem is that AI assistants usually need both. A model can read code you paste into a prompt, but that does not scale to a real repository. It loses context across files, misses relationships between symbols, and cannot reliably answer questions like:

- Where is this service initialized?
- Which functions call this method?
- What does this component import?
- Is this behavior documented anywhere near the code?
- Which part of the codebase should I inspect before changing authentication?

The `code-vector-graph` project solves that by turning a JavaScript or TypeScript repository into live, searchable documentation. Instead of asking developers to maintain another documentation site by hand, it indexes the code itself into two complementary systems:

- A vector database, Qdrant, for semantic search over code chunks.
- A graph database, Neo4j, for structural relationships between files, classes, functions, imports, calls, chunks, and glossary entries.

On top of that, it exposes a Model Context Protocol server so AI tools can query the indexed repository directly.

The result is not just "search over code." It is a live documentation layer that AI can access on demand.

## Why Code Needs More Than Text Search

Traditional code search is keyword-based. It is excellent when you know the exact function name, file path, or string literal you are looking for. But AI-assisted development often starts with fuzzy questions:

```text
How does session refresh work?
Where are API errors normalized?
What code owns the checkout flow?
Which components depend on this hook?
```

Those questions do not always match the words in the code. A function might be named `renewToken`, while a developer asks about "session refresh." A class might implement retry handling without ever using the word "resilience." Keyword search cannot reliably bridge that gap.

Vector search helps because it embeds code chunks into a semantic space. Similar ideas end up near each other, even when they use different words. But vector search alone has a weakness: it treats code mostly as text. It can find relevant chunks, but it does not naturally understand that one function calls another, a file imports a module, or a class inherits from a parent class.

That is why `code-vector-graph` combines vector search with a graph.

The vector index answers, "What code is semantically related to this question?"

The graph answers, "How is this code connected?"

Together, they give AI systems a much better map of the repository.

## The Indexing Pipeline

The pipeline starts with a target repository and turns it into searchable AI context.

At a high level, it runs this flow:

```text
Scan -> Parse -> Chunk -> Embed -> Store in Qdrant
                -> Extract graph entities -> Store in Neo4j
```

The entry point is `main.py`, which orchestrates the full pipeline. You run it against a repository:

```bash
python main.py --repo-path /path/to/your/repo --verbose
```

The scanner discovers supported JavaScript and TypeScript files:

```text
.js, .jsx, .mjs, .cjs
.ts, .tsx, .mts, .cts
```

It skips directories that should not be indexed, such as `node_modules` and `.git`, and computes file hashes so stored chunks can be identified deterministically.

Next, Tree-sitter parses each file. This matters because source code is not ordinary prose. You want a parser that understands functions, classes, imports, exports, call sites, decorators, visibility, and TypeScript-specific constructs. The parser strips comments for code chunking while preserving metadata that can later become graph context.

After parsing, the chunker splits code into token-aware chunks. The default configuration uses 400 tokens with 64 tokens of overlap. It respects line boundaries so chunks remain readable and useful when returned to a developer or an AI assistant.

Each chunk receives metadata such as:

- File path
- Language
- Start and end line
- Function or class name
- Imports and exports
- Symbols defined
- Call sites
- Visibility
- Decorators
- File hash
- Token count

That metadata is important because AI search results are only useful when they include enough context to act on. A chunk without file path and line numbers is just a quote. A chunk with symbol metadata becomes navigable documentation.

## Embeddings: Making Code Search Semantic

Once chunks are created, the embedder turns them into vectors.

This project supports two HuggingFace embedding models:

- `nomic-ai/nomic-embed-code`
- `jinaai/jina-code-embeddings-1.5b`

The default model is Nomic, which produces 3584-dimensional embeddings. Jina produces 1536-dimensional embeddings and uses task-specific prefixes for code search.

You can choose the model at indexing time:

```bash
python main.py --repo-path /path/to/your/repo --model nomic
python main.py --repo-path /path/to/your/repo --model jina
```

Each model gets its own Qdrant collection. That detail is easy to miss, but it is important. Embeddings from different models are not interchangeable because they have different dimensions and different semantic spaces. If you switch models, you re-index.

The vector store uses deterministic UUID5 IDs based on file path, chunk index, and file hash. That makes indexing idempotent: rerunning the pipeline updates the same logical records instead of creating duplicates.

This is one of the small design choices that makes the index feel like live documentation rather than a one-time dump.

## The Graph: Turning Code Structure Into Context

While chunks are embedded for semantic retrieval, the same parsed code is also converted into a code ontology graph.

Neo4j stores nodes such as:

- `File`
- `Class`
- `Function`
- `Method`
- `Field`
- `Variable`
- `Import`
- `Interface`
- `TypeAlias`
- `Chunk`
- `GlossaryEntry`

It also stores relationships such as:

- `CONTAINS`
- `CALLS`
- `IMPORTS`
- `INHERITS`
- `EXPORTS`
- `REFERENCES`
- `DEPENDS_ON`
- `HAS_GLOSSARY`

This gives AI tools a second kind of memory. They can retrieve a relevant code chunk from Qdrant, then enrich it with related graph context from Neo4j.

For example, if a query finds a function called `refreshSession`, the graph can help answer follow-up questions:

- Which file contains it?
- Which methods call it?
- What modules does the file import?
- Is it exported?
- Is there a glossary explanation attached to it?

That is the difference between "AI found some text" and "AI understands where this text lives in the system."

## Glossary Enrichment: Human Meaning Near the Code

Code structure is useful, but teams also have domain language that is not obvious from syntax alone. A variable like `riskScore`, `tenantId`, or `settlementWindow` may carry business meaning that the AST cannot infer.

This project supports glossary enrichment in two ways.

First, you can provide a manual `glossary.yml`:

```yaml
entries:
  - term: SessionManager
    kind: class
    file_path: src/auth/session.ts
    summary: Coordinates session lifecycle and token refresh behavior.
    source: manual
```

Second, comments and JSDoc near symbols can be extracted automatically:

```ts
/** Unique identifier for the authenticated user. */
const userId = session.user.id;
```

Glossary entries become `GlossaryEntry` nodes in Neo4j and searchable records in Qdrant. They are linked back to symbols with `HAS_GLOSSARY`.

This is a practical bridge between human-written documentation and code-derived documentation. Instead of asking teams to write large external docs, they can add concise explanations close to important symbols and let the indexing pipeline make them searchable.

## Hybrid Retrieval: Combining Meaning and Structure

The query layer supports three retrieval modes:

- `vector`: semantic search in Qdrant
- `graph`: graph search in Neo4j
- `hybrid`: vector plus graph search

Hybrid retrieval uses Reciprocal Rank Fusion. In simple terms, it combines ranked results from vector search and graph search into one result list. By default, vector search has a weight of `0.7` and graph search has a weight of `0.3`.

You can query from the CLI:

```bash
python query.py --question "Where is the database connection established?" --retrieval hybrid
```

You can also filter by language or file pattern:

```bash
python query.py \
  --question "What API routes exist?" \
  --retrieval hybrid \
  --language typescript \
  --file-pattern "src/routes/*"
```

This makes the index useful for both broad architectural questions and targeted code navigation.

## Making It Accessible to AI Through MCP

The final piece is the MCP server.

`mcp_server.py` exposes the indexed repository as tools that AI clients can call:

- `search_code`
- `check_health`

The `search_code` tool accepts natural language or code-like queries and supports vector, graph, and hybrid modes. It can also filter by language, file pattern, score threshold, and retrieval weights.

That means an AI coding assistant does not need to guess from stale prompt context. It can ask the repository directly:

```text
search_code(
  query="How does authentication work?",
  mode="hybrid",
  top_k=10
)
```

The tool returns formatted code chunks with locations, scores, and optional graph context. For AI-assisted development, that is extremely valuable. The model can ground its answer in retrieved code instead of relying on memory or broad assumptions.

In practice, this turns the repository into a local knowledge service.

Your codebase becomes the documentation source.

The index becomes the retrieval layer.

MCP becomes the access point for AI.

## A Practical Setup Flow

A typical setup looks like this:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with the tokens you need:

```bash
HF_TOKEN=hf_your_huggingface_token_here
OPENAI_API_KEY=sk-your_openai_key_here
```

Start the storage services:

```bash
docker-compose up -d
```

Download the embedding model:

```bash
python download_model.py
```

Run a dry run first:

```bash
python main.py --repo-path /path/to/your/repo --dry-run --verbose
```

Then index the repository:

```bash
python main.py --repo-path /path/to/your/repo --verbose
```

Ask a question:

```bash
python query.py --question "How does authentication work?" --retrieval hybrid
```

Finally, start the MCP server:

```bash
python mcp_server.py
```

After that, an MCP-compatible AI client can use the repository index as live context.

## What Makes This "Live Documentation"?

The word "documentation" usually implies something separate from the code. That separation is what makes docs decay.

This approach changes the model:

- The source code is parsed directly.
- Code chunks are embedded for semantic lookup.
- AST entities become graph nodes.
- Relationships become navigable edges.
- Glossary entries attach human meaning to symbols.
- AI clients access everything through a query tool.

When the code changes, you re-run the indexer. The documentation layer updates from the source of truth.

This does not replace architecture docs, ADRs, or human explanation. Those still matter. But it gives AI assistants a reliable way to inspect the current system before answering questions or proposing changes.

For developers, that means faster onboarding, better code discovery, and fewer hallucinated answers from AI tools.

For AI agents, it means the repository is no longer a pile of files. It is a searchable, structured, continuously refreshable knowledge base.

That is the real promise of indexing code as live documentation: not prettier docs, but better context at the moment work happens.
