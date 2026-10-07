"""FastAPI application — dashboard for code-vector-graph."""

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from code_vector_graph.api.mcp_client import init_mcp_manager, shutdown_mcp_manager
from code_vector_graph.api.routers import apps, chat, graph, health, qdrant, search

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# `<!-- @include views/overview.html -->` markers in index.html are replaced with the
# referenced file (relative to STATIC_DIR) at request time — a no-build SPA shell.
_INCLUDE_RE = re.compile(r"<!--\s*@include\s+([\w./-]+)\s*-->")


def _render_index(static_dir: Path = STATIC_DIR) -> str:
    """Read index.html and expand its @include markers (per request; cheap, reload-friendly)."""
    html = (static_dir / "index.html").read_text(encoding="utf-8")

    def _sub(match: re.Match) -> str:
        rel = match.group(1)
        parts = [p for p in rel.replace("\\", "/").split("/") if p]
        if not parts or ".." in parts:
            return f"<!-- missing: {rel} -->"
        target = static_dir.joinpath(*parts)
        try:
            return target.read_text(encoding="utf-8")
        except OSError:
            logger.warning("index.html includes missing partial %s", rel)
            return f"<!-- missing: {rel} -->"

    return _INCLUDE_RE.sub(_sub, html)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MCP session manager…")
    try:
        manager = await init_mcp_manager()
        logger.info("MCP session ready. Tools: %s", [t.name for t in manager._tool_schemas])
    except Exception as e:
        logger.error("Failed to start MCP session: %s — dashboard will run in degraded mode", e)

    yield

    logger.info("Shutting down MCP session…")
    await shutdown_mcp_manager()


app = FastAPI(
    title="Code Vector Graph Dashboard",
    description="Web interface for exploring Qdrant vectors and Neo4j code graph",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(apps.router, prefix="/api", tags=["apps"])
app.include_router(qdrant.router, prefix="/api", tags=["qdrant"])
app.include_router(graph.router, prefix="/api", tags=["graph"])
app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(chat.router, prefix="/api", tags=["chat"])

# Static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return HTMLResponse(_render_index())
