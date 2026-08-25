# Setup

## Prerequisites

- Python 3.10+
- Docker & Docker Compose
- HuggingFace token (for model access)
- OpenAI API key (for RAG answers via `cvg-query` — optional)
- DeepSeek API key (for the OKF LLM wiki via `cvg-okf-build` — optional)

## Step-by-Step Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd code-vector-graph
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate        # Windows
```

### 3. Install dependencies

```bash
pip install -e ".[ingest,serve,query,mcp,dev]"
```

This installs PyTorch, Transformers, Tree-sitter, Qdrant client, and all other required packages.

### 4. Create a `.env` file

```bash
cat > .env << 'EOF'
HF_TOKEN=hf_your_huggingface_token_here
OPENAI_API_KEY=sk-your_openai_key_here
DEEPSEEK_API_KEY=sk-your_deepseek_key_here
EOF
```

- **HF_TOKEN**: HuggingFace token with access to the embedding models. Get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). Both models require `trust_remote_code=True`, so ensure your token has read access.
- **OPENAI_API_KEY**: OpenAI API key for RAG answers via `cvg-query` (only needed for querying, not indexing).
- **DEEPSEEK_API_KEY**: DeepSeek API key for the OKF LLM wiki via `cvg-okf-build` (only needed for wiki generation). Get one at [platform.deepseek.com](https://platform.deepseek.com/).

### 5. Start infrastructure services

```bash
docker-compose up -d
```

This starts:
- **Qdrant** (Vector Database): REST API at `http://localhost:6333`, gRPC at `http://localhost:6334`
- **Neo4j** (Graph Database): Browser at `http://localhost:7474`, Bolt at `bolt://localhost:7687`

Verify they're running:
```bash
curl http://localhost:6333/healthz        # Qdrant health check
docker-compose ps neo4j                   # Neo4j status
```

### 6. Download the embedding model

You must download the model you plan to use before running the pipeline. The script supports both models:

```bash
# Download the default Nomic model (~28GB on disk — 7B params in fp32):
cvg-download-model

# Or download the Jina model (~3GB, recommended for laptops):
cvg-download-model --model jina
```

Models are cached in `~/.cache/huggingface/` for subsequent runs. Add
`--no-smoke-test` to only fetch the files without loading the weights into RAM
(useful in CI or on low-memory machines).

### 7. Index a repository

```bash
# With default Nomic model:
cvg-ingest --repo-path /path/to/your/repo --verbose

# With Jina model:
cvg-ingest --repo-path /path/to/your/repo --model jina --verbose

# Dry run first (no embeddings, no storage):
cvg-ingest --repo-path /path/to/your/repo --dry-run --verbose
```

### 8. Query your indexed code

```bash
# Vector search (requires OPENAI_API_KEY for RAG answers):
cvg-query --question "How does authentication work?"

# Hybrid search (vector + graph):
cvg-query --question "Where is the database connection established?" --retrieval hybrid
```

### 9. (Optional) Start the MCP server

```bash
cvg-mcp
```

See the [MCP Server](#mcp-server) section for client configuration.


## Quick Start Summary


```bash
# 1. Clone and enter the project
git clone <repository-url> && cd code-vector-graph

# 2. Create virtual environment and install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ingest,serve,query,mcp,dev]"

# 3. Configure — create .env with your tokens
cat > .env << 'EOF'
HF_TOKEN=hf_your_huggingface_token
OPENAI_API_KEY=sk_your_openai_key
EOF

# 4. Start services (Qdrant + Neo4j)
docker-compose up -d

# 5. Download embedding model (Nomic by default)
cvg-download-model

# 6. Index a repository
cvg-ingest --repo-path /path/to/repo --verbose

# 7. Query with RAG
cvg-query --question "How does auth work?" --retrieval hybrid

# 8. Or start MCP server for AI client integration
cvg-mcp

# 9. (Optional) Build the OKF LLM wiki (needs DEEPSEEK_API_KEY) and sync it back
cvg-okf-build --repo-path /path/to/repo --verbose
cvg-okf-sync --bundle okf-wiki --verbose
```

