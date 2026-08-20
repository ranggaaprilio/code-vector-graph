---
name: indexed-repos
description: Which codebases are indexed in the code-vector-graph Qdrant/Neo4j store, beyond this repo itself
metadata:
  type: reference
---

The code-vector-graph MCP index is not limited to the code-vector-graph repo itself — it also contains other codebases the user has indexed separately, queryable through the same `search_code`/`search_code_json` tools.

Known indexed repos so far:
- `/Users/ranggaaprilioutama/Repository/poc/white-board` — "White Board" collaborative whiteboard app: Next.js (App Router) + Liveblocks (real-time canvas) + Convex (backend/data) + Clerk (auth/orgs). Convex schema lives at `convex/schema.ts` (tables: `boards`, `userFavorites`); board CRUD/favorites logic in `convex/board.ts`; dashboard listing query in `convex/boards.ts`; dashboard UI under `app/dashboard/_components/`.

**How to apply:** When the user's query is clearly about a different product/domain than code-vector-graph itself (e.g. mentions "white-board", "Liveblocks", "Convex", "Clerk boards"), don't assume the index is empty — query it directly; results will carry the real absolute file paths (e.g. under `/Users/ranggaaprilioutama/Repository/poc/white-board/...`) telling you which repo they came from. Treat this list as a hint, not a guarantee — verify current file paths via search results rather than assuming these files still exist unchanged.
