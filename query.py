"""Query script for asking questions about indexed code."""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from src.cli import setup_logging
from src.config import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_MODEL_ID,
    DEFAULT_QDRANT_URL,
    get_model_config,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
)
from src.embedder import create_embedder
from src.graph_store import GraphStore
from src.hybrid_retriever import HybridRetriever
from src.store import VectorStore, get_collection_name

logger = logging.getLogger(__name__)


def expand_code_query(query: str) -> str:
    """Expand query with code-specific terminology for better retrieval.

    Examples:
        - "function" -> also searches for "def", "method"
        - "class" -> also searches for "interface", "type"
        - "import" -> also searches for "require", "from"
    """
    expansions = {
        "function": ["def", "method", "func"],
        "class": ["interface", "type", "struct"],
        "import": ["require", "from", "include"],
        "variable": ["var", "let", "const"],
        "error": ["exception", "throw", "catch"],
        "test": ["spec", "it(", "describe("],
        "async": ["await", "promise", "then"],
        "export": ["module.exports", "export default"],
    }

    query_lower = query.lower()
    expanded_terms = [query]

    for term, alternatives in expansions.items():
        if term in query_lower:
            for alt in alternatives:
                if alt not in query_lower:
                    expanded_terms.append(alt)

    return " ".join(expanded_terms) if len(expanded_terms) > 1 else query


def parse_query_args() -> argparse.Namespace:
    """Parse command line arguments for the query script."""
    parser = argparse.ArgumentParser(
        prog="code-query",
        description="Ask questions about your indexed code using RAG + OpenAI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --question "How does authentication work?"
  %(prog)s --question "..." --top-k 10 --verbose
        """.strip(),
    )

    parser.add_argument(
        "--question",
        type=str,
        required=True,
        help="Your question about the code",
    )

    parser.add_argument(
        "--qdrant-url",
        type=str,
        default=DEFAULT_QDRANT_URL,
        help=f"Qdrant server URL (default: {DEFAULT_QDRANT_URL})",
    )

    parser.add_argument(
        "--collection-name",
        type=str,
        default=DEFAULT_COLLECTION_NAME,
        help=f"Base Qdrant collection name (default: {DEFAULT_COLLECTION_NAME})",
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="Number of top code chunks to retrieve (default: 20)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress info",
    )

    parser.add_argument(
        "--retrieval",
        type=str,
        choices=["vector", "hybrid", "graph"],
        default="vector",
        help="Retrieval mode: vector (default), hybrid (vector+graph with RRF fusion), or graph (Neo4j only)",
    )

    parser.add_argument(
        "--file-pattern",
        type=str,
        default=None,
        help="Filter results by file path pattern (e.g., '*.ts', 'src/components/*')",
    )

    parser.add_argument(
        "--language",
        type=str,
        choices=["javascript", "typescript", "tsx"],
        default=None,
        help="Filter results by programming language",
    )

    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Minimum similarity score threshold (0.0-1.0). Higher values = more relevant but fewer results",
    )

    parser.add_argument(
        "--expand-query",
        action="store_true",
        help="Expand query with code-specific synonyms (e.g., 'function' -> 'def', 'method')",
    )

    parser.add_argument(
        "--vector-weight",
        type=float,
        default=0.7,
        help="Weight for vector search in hybrid mode (default: 0.7)",
    )

    parser.add_argument(
        "--graph-weight",
        type=float,
        default=0.3,
        help="Weight for graph search in hybrid mode (default: 0.3)",
    )

    parser.add_argument(
        "--neo4j-uri",
        type=str,
        default=NEO4J_URI,
        help=f"Neo4j bolt URI (default: {NEO4J_URI})",
    )

    parser.add_argument(
        "--neo4j-user",
        type=str,
        default=NEO4J_USER,
        help=f"Neo4j username (default: {NEO4J_USER})",
    )

    parser.add_argument(
        "--neo4j-password",
        type=str,
        default=NEO4J_PASSWORD,
        help="Neo4j password (default: from config)",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point for the query CLI."""
    args = parse_query_args()
    setup_logging(args.verbose)

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.error("OPENAI_API_KEY environment variable not set")
        print(
            "ERROR: OPENAI_API_KEY environment variable is required.",
            file=sys.stderr,
        )
        print(
            "Set it before running: export OPENAI_API_KEY='your-key'",
            file=sys.stderr,
        )
        return 1

    embedder = create_embedder(model_id=DEFAULT_MODEL_ID)

    if not embedder.check_health():
        logger.error("Embedder health check failed")
        print("ERROR: HuggingFace embedder is not available.", file=sys.stderr)
        return 1
    logger.info("Embedder health check passed")

    query_text = args.question
    if args.expand_query:
        query_text = expand_code_query(args.question)
        logger.info(f"Expanded query: {query_text}")
    logger.info(f"Embedding question: {query_text}")
    query_vector = embedder.embed_query(query_text)
    logger.info(f"Query vector: {query_vector}")

    model_config = get_model_config(DEFAULT_MODEL_ID)
    dimensions = model_config["dimensions"]
    collection_name = get_collection_name(args.collection_name, "huggingface", model=model_config["model_name"])
    store = VectorStore(
        collection_name=collection_name,
        qdrant_url=args.qdrant_url,
        embedding_dimensions=dimensions,
    )

    logger.info("Checking Qdrant health...")
    if not store.check_health():
        logger.error("Qdrant health check failed")
        print(
            "ERROR: Cannot connect to Qdrant server.",
            file=sys.stderr,
        )
        return 1
    logger.info("Qdrant health check passed")

    results = []

    if args.retrieval == "vector":
        logger.info(f"Using vector search for top {args.top_k} results...")

        from qdrant_client.models import FieldCondition, Filter, MatchValue

        query_filter = None
        filter_conditions = []

        if args.language:
            filter_conditions.append(
                FieldCondition(key="language", match=MatchValue(value=args.language))
            )
            logger.info(f"Filtering by language: {args.language}")

        if filter_conditions:
            query_filter = Filter(must=filter_conditions)

        try:
            results = store.search(
                query_vector, top_k=args.top_k, query_filter=query_filter
            )

            # Apply file pattern filter if specified
            if args.file_pattern:
                import fnmatch

                results = [
                    r
                    for r in results
                    if fnmatch.fnmatch(
                        r.get("payload", {}).get("file_path", ""), args.file_pattern
                    )
                ]
                logger.info(f"After file pattern filter: {len(results)} results")

            # Apply score threshold filter
            if args.min_score > 0:
                results = [r for r in results if r.get("score", 0) >= args.min_score]
                logger.info(
                    f"After score threshold ({args.min_score}): {len(results)} results"
                )

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            error_msg = str(e).lower()
            if "not found" in error_msg or "doesn't exist" in error_msg:
                print(
                    f"ERROR: Collection '{collection_name}' not found in Qdrant.",
                    file=sys.stderr,
                )
                print("\nTroubleshooting:", file=sys.stderr)
                print(
                    "  1. Ensure you've indexed the repository first:", file=sys.stderr
                )
                print(
                    "     python main.py --repo-path /path/to/repo",
                    file=sys.stderr,
                )
                print("  2. Check the collection name matches:", file=sys.stderr)
                print(f"     --collection-name {args.collection_name}", file=sys.stderr)
                print(
                    "  3. Verify Qdrant has the data: curl http://localhost:6333/collections",
                    file=sys.stderr,
                )
            elif "dimension" in error_msg or "shape" in error_msg:
                print(f"ERROR: Embedding dimension mismatch.", file=sys.stderr)
                print("\nTroubleshooting:", file=sys.stderr)
                print(
                    "  The query embedding dimensions don't match the indexed data.",
                    file=sys.stderr,
                )
                print(f"  Current: {len(query_vector)} dimensions", file=sys.stderr)
                print(f"  Expected: {dimensions} dimensions", file=sys.stderr)
                print(
                    "\n  Re-index the repository to ensure dimension compatibility:",
                    file=sys.stderr,
                )
                print(
                    "     python main.py --repo-path /path/to/repo",
                    file=sys.stderr,
                )
            else:
                print(f"ERROR: Failed to search Qdrant: {e}", file=sys.stderr)
            return 1

    elif args.retrieval == "graph":
        logger.info("Using graph search mode")
        graph_store = GraphStore(
            uri=args.neo4j_uri,
            user=args.neo4j_user,
            password=args.neo4j_password,
        )
        try:
            if not graph_store.check_health():
                logger.error("Neo4j health check failed")
                print("ERROR: Cannot connect to Neo4j server.", file=sys.stderr)
                print("\nTroubleshooting:", file=sys.stderr)
                print(
                    "  1. Ensure Neo4j is running: docker ps | grep neo4j",
                    file=sys.stderr,
                )
                print(
                    "  2. Check connection URI: --neo4j-uri bolt://localhost:7687",
                    file=sys.stderr,
                )
                print(
                    "  3. Verify credentials in .env or command line args",
                    file=sys.stderr,
                )
                return 1
            logger.info("Neo4j health check passed")
        except Exception as e:
            logger.error(f"Neo4j health check failed: {e}")
            print(f"ERROR: Cannot connect to Neo4j: {e}", file=sys.stderr)
            return 1

        # Enhanced graph search with multiple query patterns
        query_lower = args.question.lower()
        search_terms = [args.question] + query_lower.split()

        # Try multiple search strategies
        cypher_queries = [
            # Strategy 1: Direct name/path match (case-insensitive)
            (
                """
            MATCH (n)
            WHERE toLower(n.name) CONTAINS toLower($query)
               OR toLower(n.path) CONTAINS toLower($query)
            RETURN n, 1.0 as score
            LIMIT $limit
            """,
                {"query": args.question, "limit": args.top_k},
            ),
            # Strategy 2: Search in related nodes (any relationship type)
            # Using generic relationship pattern to work with any graph structure
            (
                """
            MATCH (n)-->(related)
            WHERE toLower(related.name) CONTAINS toLower($query)
            RETURN n, 0.8 as score
            LIMIT $limit
            """,
                {"query": args.question, "limit": args.top_k},
            ),
            # Strategy 3: Search by node label type (Function, Class, etc.)
            (
                """
            MATCH (n)
            WHERE any(label IN labels(n) WHERE toLower(label) CONTAINS toLower($query))
            RETURN n, 0.6 as score
            LIMIT $limit
            """,
                {"query": args.question, "limit": args.top_k},
            ),
        ]

        all_results = []
        seen_ids = set()

        for cypher, params in cypher_queries:
            try:
                result = graph_store.query_graph(cypher, params)
                # Handle Neo4j Result object - extract records properly
                records = result.records if hasattr(result, "records") else result
                for record in records:
                    # Handle different result formats
                    if hasattr(record, "get"):
                        node = record.get("n")
                        score = record.get("score", 1.0)
                    elif isinstance(record, dict):
                        node = record.get("n")
                        score = record.get("score", 1.0)
                    elif isinstance(record, (list, tuple)) and len(record) >= 2:
                        node = record[0]
                        score = record[1] if len(record) > 1 else 1.0
                    else:
                        continue

                    if node is None:
                        continue

                    # Convert node to dict
                    if hasattr(node, "items"):
                        node_data = dict(node.items())
                    elif hasattr(node, "_properties"):
                        node_data = dict(node._properties)
                    elif isinstance(node, dict):
                        node_data = node
                    else:
                        node_data = {"value": str(node)}

                    node_id = (
                        node_data.get("id") or node_data.get("name") or str(id(node))
                    )
                    if node_id not in seen_ids:
                        seen_ids.add(node_id)
                        all_results.append(
                            {
                                "id": node_id,
                                "payload": node_data,
                                "score": score,
                                "graph_context": None,
                            }
                        )
            except Exception as e:
                logger.warning(f"Graph search strategy failed: {e}")
                import traceback

                logger.debug(f"Traceback: {traceback.format_exc()}")
                continue

        # Sort by score and limit results
        all_results.sort(key=lambda x: x["score"], reverse=True)
        results = all_results[: args.top_k]

        if not results:
            logger.warning("No graph results found with any search strategy")

    elif args.retrieval == "hybrid":
        logger.info(f"Using hybrid retrieval for top {args.top_k} results...")
        graph_store = GraphStore(
            uri=args.neo4j_uri,
            user=args.neo4j_user,
            password=args.neo4j_password,
        )
        try:
            if not graph_store.check_health():
                logger.error("Neo4j health check failed")
                print("ERROR: Cannot connect to Neo4j server.", file=sys.stderr)
                return 1
            logger.info("Neo4j health check passed")
        except Exception as e:
            logger.error(f"Neo4j health check failed: {e}")
            print(f"ERROR: Cannot connect to Neo4j: {e}", file=sys.stderr)
            return 1

        hybrid = HybridRetriever(store, graph_store, embedder)
        try:
            results = hybrid.search(
                args.question,
                mode="hybrid",
                top_k=args.top_k,
                vector_weight=args.vector_weight,
                graph_weight=args.graph_weight,
                query_vec=query_vector,
            )
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            print(f"ERROR: Failed to perform hybrid search: {e}", file=sys.stderr)
            return 1

    if not results:
        print("No relevant code found.")
        return 0

    logger.info(f"Retrieved {len(results)} relevant chunks")

    # Deduplicate results by file_path + function_name to avoid redundant context
    seen_signatures = set()
    unique_results = []
    for r in results:
        if isinstance(r, dict):
            payload = r.get("payload", {}) or {}
        else:
            payload = {}
        file_path = payload.get("file_path", "unknown")
        func_name = payload.get("function_name")
        signature = (file_path, func_name)
        if signature not in seen_signatures:
            seen_signatures.add(signature)
            unique_results.append(r)

    logger.info(f"After deduplication: {len(unique_results)} unique chunks")

    context_parts = []
    for r in unique_results:
        if isinstance(r, dict):
            payload = r.get("payload", {})
            if payload is None:
                payload = {}
        else:
            payload = {}
        file_path = payload.get("file_path", "unknown")
        text = payload.get("text_content", "")
        if text:
            context_parts.append(f"[file: {file_path}]\n```\n{text}\n```")
        if isinstance(r, dict) and r.get("graph_context"):
            graph_ctx = r["graph_context"]
            if isinstance(graph_ctx, list):
                ctx_str = "; ".join(str(item) for item in graph_ctx)
            else:
                ctx_str = str(graph_ctx)
            context_parts.append(f"[graph context: {ctx_str}]")

    context = "\n\n".join(context_parts)

    # Send to OpenAI
    from openai import OpenAI

    client = OpenAI(api_key=openai_api_key)

    system_prompt = (
        "You are a code assistant. Use the provided code snippets to answer "
        "the user's question. Reference file paths when relevant. If the answer "
        "isn't in the snippets, say so. do not make up an answer. just answer based on the snippets!."
    )

    user_message = f"Context:\n{context}\n\nQuestion: {args.question}"

    logger.info(f"User message: {user_message}")

    logger.info("Sending to OpenAI gpt-4o-mini...")
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
        )
    except Exception as e:
        logger.error(f"OpenAI API call failed: {e}")
        print(f"ERROR: OpenAI API call failed: {e}", file=sys.stderr)
        return 1

    answer = response.choices[0].message.content
    print(answer)

    return 0


if __name__ == "__main__":
    sys.exit(main())
