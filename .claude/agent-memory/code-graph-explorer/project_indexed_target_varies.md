---
name: project_indexed_target_varies
description: The Qdrant/Neo4j index target is whatever was last indexed by the user, not always code-vector-graph itself
type: project
---

The code-vector-graph MCP's Qdrant/Neo4j index does not always point at the code-vector-graph
repo itself. It indexes whatever external codebase the user last ran the indexer against. As of
2026-07-08, a query session returned results entirely from a separate repo:
`/Users/ranggaaprilioutama/Repository/poc/white-board` — a Next.js + Liveblocks + Convex + Clerk
real-time collaborative whiteboard app (not part of code-vector-graph).

**Why:** The code-graph-explorer agent is invoked generically to "explore the codebase" via MCP
search tools, but the actual indexed content is external and can change between sessions.

**How to apply:** Before assuming search results describe code-vector-graph's own architecture,
check the file paths returned by search_code — if they resolve to a different repo path (e.g.
`.../poc/white-board/...` instead of `.../poc/code-vector-graph/...`), treat the results as
describing that external project, not code-vector-graph. See [[whiteboard_app_architecture]] for
a snapshot of the white-board app's structure (verify paths still exist before relying on it, as
this is a point-in-time snapshot).
