import logging
from neo4j import GraphDatabase
from src.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE
from src.graph_schema import NODE_LABELS

logger = logging.getLogger(__name__)
NAME = __name__

# Number of records to process in a single batch for ingestion
BATCH_SIZE = 500


class GraphStore:
    def __init__(self, uri: str | None = None, user: str | None = None,
                 password: str | None = None, database: str | None = None):
        self.uri = uri or NEO4J_URI
        self.user = user or NEO4J_USER
        self.password = password or NEO4J_PASSWORD
        self.database = database or NEO4J_DATABASE
        # The tests patch GraphDatabase.driver, so we delegate directly here
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))

    def check_health(self) -> bool:
        try:
            self.driver.verify_connectivity()
            return True
        except Exception as exc:
            logger.error(f"Neo4j health check failed: {exc}")
            return False

    def create_constraints(self):
        # Create a unique constraint for id on every known node label
        for label in NODE_LABELS:
            cypher = f"""
            CREATE CONSTRAINT {label.lower()}_id_unique IF NOT EXISTS
            FOR (n:{label}) REQUIRE n.id IS UNIQUE
            """
            # Tests only assert presence of the CREATE CONSTRAINT and IS UNIQUE
            self.driver.execute_query(cypher)

    def upsert_nodes(self, nodes):
        # Group by label to allow per-label MERGE with the proper label in Cypher
        by_label = {}
        for n in nodes:
            lbl = n.get("label")
            by_label.setdefault(lbl, []).append(n)

        for label, batch_nodes in by_label.items():
            for i in range(0, len(batch_nodes), BATCH_SIZE):
                batch = batch_nodes[i:i + BATCH_SIZE]
                cypher = f"""
                UNWIND $batch AS item
                MERGE (n:{label} {{id: item.id}})
                SET n += item.properties
                """
                self.driver.execute_query(cypher, {"batch": batch})

    def upsert_relationships(self, relationships):
        # Group by relationship type so we can use the actual type in Cypher.
        # Neo4j doesn't support parameterized relationship types, so we batch per type.
        by_type = {}
        for rel in relationships:
            rel_type = rel.get("type", "REFERENCES")
            by_type.setdefault(rel_type, []).append(rel)

        for rel_type, batch_rels in by_type.items():
            for i in range(0, len(batch_rels), BATCH_SIZE):
                batch = batch_rels[i:i + BATCH_SIZE]
                cypher = f"""
                UNWIND $batch AS item
                MATCH (s {{id: item.source_id}})
                MATCH (t {{id: item.target_id}})
                MERGE (s)-[r:{rel_type}]->(t)
                SET r += item.properties
                """
                self.driver.execute_query(cypher, {"batch": batch})

    def query_graph(self, cypher: str, params: dict | None = None):
        # Return the raw result records for caller to interpret
        return self.driver.execute_query(cypher, params or {})

    def get_related_nodes(self, node_id: str, depth: int = 1, limit: int = 10):
        cypher = f"""
        MATCH path = (start {{id: $node_id}})-[*1..{depth}]->(related)
        RETURN related, relationships(path) as rels
        LIMIT $limit
        """
        return self.driver.execute_query(cypher, {"node_id": node_id, "limit": limit})

    def close(self):
        self.driver.close()
