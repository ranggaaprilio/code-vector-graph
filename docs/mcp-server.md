# MCP Server (`cvg-mcp`)

The project includes an MCP (Model Context Protocol) server that exposes code search as tools for AI clients like Claude Desktop or OpenCode.

#### Configure in Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "code-vector-graph": {
      "type": "stdio",
      "command": "/path/to/code-vector-graph/.venv/bin/python",
      "args": ["/path/to/code-vector-graph/cvg-mcp"]
    }
  }
}
```

#### Configure in OpenCode

The project includes `.mcp.json` — OpenCode picks this up automatically.

#### Available MCP Tools

| Tool | Description |
|------|-------------|
| `search_code` | Search indexed code using vector embeddings and/or graph relationships. Supports `vector`, `hybrid` (recommended), and `graph` modes. |
| `check_health` | Check connectivity of embedder (model + device), Qdrant, and Neo4j |

#### `search_code` Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `query` | *required* | Natural language or code search query |
| `mode` | `hybrid` | `vector`, `hybrid` (recommended, RRF fusion), or `graph` |
| `top_k` | `10` | Number of results |
| `language` | *none* | Filter: `javascript`, `typescript`, `tsx` |
| `file_pattern` | *none* | File path glob filter |
| `min_score` | `0.0` | Minimum similarity score |
| `vector_weight` | `0.7` | Vector weight (hybrid mode) |
| `graph_weight` | `0.3` | Graph weight (hybrid mode) |

