# code-graph-explorer Agent

**OpenCode Subagent Type:** `code-graph-explorer`  
**Claude Agent:** `.claude/agents/code-graph-explorer.md`

## Description

Use this agent when you need to understand code structure, trace execution flows, discover relationships between code components, or get summarized insights about a codebase by querying the code-vector-graph MCP.

This agent is ideal when you need to answer questions like:
- "How does this feature work?"
- "What calls this function?"
- "Where is this logic implemented?"
- "What is the flow for this operation?"

## Usage

### OpenCode

```python
task(
    subagent_type="code-graph-explorer",
    load_skills=[],
    prompt="""
    [CONTEXT]: Brief context about the codebase and what you're investigating
    
    [GOAL]: What specific information you need (function flow, architecture, dependencies, etc.)
    
    [REQUEST]: The specific question or target to investigate
    """,
    run_in_background=False
)
```

### Examples

**Understanding a feature flow:**
```python
task(
    subagent_type="code-graph-explorer",
    load_skills=[],
    prompt="""
    Context: Developer is trying to understand how authentication works in the codebase.
    
    Goal: Trace the authentication flow from login to session validation.
    
    Request: Can you explain how the user authentication flow works in our codebase?
    """,
    run_in_background=False
)
```

**Finding function usage:**
```python
task(
    subagent_type="code-graph-explorer",
    load_skills=[],
    prompt="""
    Context: A developer wants to know where a specific function is used across the project.
    
    Goal: Find all usages and dependencies of the processPayment function.
    
    Request: Where is the `processPayment` function used and what does it depend on?
    """,
    run_in_background=False
)
```

**Architecture overview:**
```python
task(
    subagent_type="code-graph-explorer",
    load_skills=[],
    prompt="""
    Context: A developer is onboarding and wants to understand the overall architecture of a module.
    
    Goal: Provide a high-level overview of the notification module structure.
    
    Request: Give me an overview of how the notification module is structured and what it connects to.
    """,
    run_in_background=False
)
```

## Core Capabilities

This agent operates exclusively using the **code-vector-graph MCP** tools:
- `code-vector-graph_search_code` - Search codebase using vector embeddings and graph relationships
- `code-vector-graph_check_health` - Verify MCP service connectivity

### Workflow

1. **Clarify Intent** - Parse the question to identify target, insight type, and scope
2. **Query the MCP** - Use `search_code` with targeted queries
3. **Synthesize & Summarize** - Transform results into structured, informative summaries
4. **Highlight Insights** - Surface patterns, dependencies, and architectural decisions

### Tool Constraints

- **Only use**: `code-vector-graph_search_code` and `code-vector-graph_check_health`
- **Never use**: Bash, Read, Write, Edit, grep, or filesystem tools
- If MCP returns no results, suggest refined queries
- If information is not in the graph index, explicitly state so

## MCP Search Parameters

When using `code-vector-graph_search_code`:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `query` | Natural language or code search query | "user authentication flow" |
| `mode` | Retrieval mode: "vector", "hybrid", "graph" | "hybrid" (recommended) |
| `top_k` | Number of code chunks to return | 10 |
| `language` | Filter by language | "typescript", "python" |
| `file_pattern` | Filter by file path glob | "src/components/*" |
| `min_score` | Minimum similarity score (0.0-1.0) | 0.7 |

## Best Practices

1. **Be Specific**: Target exact functions, classes, or modules
2. **Multi-Query**: Break complex questions into multiple targeted searches
3. **Iterate**: Use initial results to refine subsequent queries
4. **Contextualize**: Explain why relationships matter, not just that they exist
5. **Cite Sources**: Always reference file paths and line numbers from results

## Cross-IDE Compatibility

This agent definition works across both IDEs:

| Feature | OpenCode | Claude Code |
|---------|----------|-------------|
| Invocation | `task(subagent_type="code-graph-explorer", ...)` | `/agent code-graph-explorer` |
| Location | `.opencode/agents/` | `.claude/agents/` |
| Format | Markdown + Prompt | Markdown + YAML Frontmatter |
| Tools | Built-in MCP | MCP via `mcp__` prefix |

## See Also

- [Project AGENTS.md](/AGENTS.md) - Main project agent documentation
- [Claude Agent Definition](../.claude/agents/code-graph-explorer.md) - Claude-specific version
- [MCP Server](../mcp_server.py) - code-vector-graph MCP implementation
