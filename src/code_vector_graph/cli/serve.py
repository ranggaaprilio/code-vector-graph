"""`cvg-serve` — run the dashboard (FastAPI + static SPA) with uvicorn."""

import argparse
import sys


def create_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cvg-serve",
        description="Serve the code-vector-graph web dashboard.",
    )
    p.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    p.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    return p


def main() -> int:
    args = create_parser().parse_args()

    import uvicorn

    # Passed as an import string so --reload can re-import the app on change.
    uvicorn.run(
        "code_vector_graph.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
