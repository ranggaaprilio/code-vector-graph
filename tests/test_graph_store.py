import unittest
from unittest.mock import patch, MagicMock

import pytest

from src.graph_schema import NODE_LABELS
from src.graph_store import GraphStore


class FakeCounters:
    nodes_created = 2
    relationships_created = 1
    properties_set = 3


class FakeSummary:
    counters = FakeCounters()


class TestGraphStore:
    @patch('src.graph_store.GraphDatabase.driver')
    def test_init(self, mock_driver_class):
        mock_driver = MagicMock()
        mock_driver_class.return_value = mock_driver

        gs = GraphStore(uri="bolt://localhost:7687", user="neo4j", password="test")

        mock_driver_class.assert_called_once_with("bolt://localhost:7687", auth=("neo4j", "test"))
        assert gs.driver == mock_driver

    @patch('src.graph_store.GraphDatabase.driver')
    def test_check_health(self, mock_driver_class):
        mock_driver = MagicMock()
        mock_driver_class.return_value = mock_driver

        gs = GraphStore()
        gs.check_health()
        mock_driver.verify_connectivity.assert_called_once()

    @patch('src.graph_store.GraphDatabase.driver')
    def test_create_constraints(self, mock_driver_class):
        mock_driver = MagicMock()
        mock_driver_class.return_value = mock_driver

        gs = GraphStore()
        gs.create_constraints()

        # Verify execute_query called for each label
        calls = mock_driver.execute_query.call_args_list
        assert len(calls) == len(NODE_LABELS)

        # Verify each cypher contains CREATE CONSTRAINT and IS UNIQUE
        for call_args in calls:
            cypher = call_args[0][0]
            assert "CREATE CONSTRAINT" in cypher
            assert "IS UNIQUE" in cypher
            assert call_args.kwargs["database_"] == "neo4j"

    @patch('src.graph_store.GraphDatabase.driver')
    def test_upsert_nodes(self, mock_driver_class):
        mock_driver = MagicMock()
        mock_driver_class.return_value = mock_driver

        gs = GraphStore()
        nodes = [
            {"label": "File", "id": "uuid1", "properties": {"path": "test.js"}},
            {"label": "Class", "id": "uuid2", "properties": {"name": "MyClass"}},
        ]
        mock_driver.execute_query.return_value = ([], FakeSummary(), [])
        counts = gs.upsert_nodes(nodes)

        cypher = mock_driver.execute_query.call_args[0][0]
        assert "UNWIND" in cypher
        assert "MERGE" in cypher  # ensure idempotent upsert
        assert "CREATE" not in cypher
        assert counts["attempted_nodes"] == 2
        assert counts["nodes_created"] == 4
        assert mock_driver.execute_query.call_args.kwargs["database_"] == "neo4j"

    @patch('src.graph_store.GraphDatabase.driver')
    def test_upsert_nodes_rejects_unknown_label(self, mock_driver_class):
        mock_driver = MagicMock()
        mock_driver_class.return_value = mock_driver

        gs = GraphStore()
        nodes = [{"label": "File`) DETACH DELETE n //", "id": "uuid1", "properties": {}}]

        with pytest.raises(ValueError, match="Unknown Neo4j node label"):
            gs.upsert_nodes(nodes)

        mock_driver.execute_query.assert_not_called()

    @patch('src.graph_store.GraphDatabase.driver')
    def test_upsert_nodes_rejects_missing_id(self, mock_driver_class):
        mock_driver = MagicMock()
        mock_driver_class.return_value = mock_driver

        gs = GraphStore()
        nodes = [{"label": "File", "properties": {}}]

        with pytest.raises(ValueError, match="missing id"):
            gs.upsert_nodes(nodes)

        mock_driver.execute_query.assert_not_called()

    @patch('src.graph_store.GraphDatabase.driver')
    def test_upsert_relationships(self, mock_driver_class):
        mock_driver = MagicMock()
        mock_driver_class.return_value = mock_driver

        gs = GraphStore()
        batch = [
            {"source_id": "s1", "target_id": "t1", "properties": {"weight": 0.5}},
        ]
        mock_driver.execute_query.return_value = ([], FakeSummary(), [])
        counts = gs.upsert_relationships(batch)

        cypher = mock_driver.execute_query.call_args[0][0]
        assert "UNWIND" in cypher
        assert "MERGE" in cypher
        assert "CREATE" not in cypher
        assert counts["attempted_relationships"] == 1
        assert counts["relationships_created"] == 1
        assert mock_driver.execute_query.call_args.kwargs["database_"] == "neo4j"

    @patch('src.graph_store.GraphDatabase.driver')
    def test_upsert_relationships_rejects_unknown_type(self, mock_driver_class):
        mock_driver = MagicMock()
        mock_driver_class.return_value = mock_driver

        gs = GraphStore()
        batch = [
            {"type": "CALLS`) DELETE r //", "source_id": "s1", "target_id": "t1", "properties": {}},
        ]

        with pytest.raises(ValueError, match="Unknown Neo4j relationship type"):
            gs.upsert_relationships(batch)

        mock_driver.execute_query.assert_not_called()

    @patch('src.graph_store.GraphDatabase.driver')
    def test_query_graph(self, mock_driver_class):
        mock_driver = MagicMock()
        mock_driver_class.return_value = mock_driver

        gs = GraphStore()
        query = "MATCH (n) RETURN n"
        params = {"limit": 10}
        gs.query_graph(query, params)
        mock_driver.execute_query.assert_called_with(query, params, database_="neo4j")

    @patch('src.graph_store.GraphDatabase.driver')
    def test_get_related_nodes(self, mock_driver_class):
        mock_driver = MagicMock()
        mock_driver_class.return_value = mock_driver

        gs = GraphStore()
        start_id = "uuid0"
        depth = 2
        gs.get_related_nodes(start_id, depth)
        cypher = mock_driver.execute_query.call_args[0][0]
        assert "MATCH" in cypher
        assert "RETURN" in cypher

    @patch('src.graph_store.GraphDatabase.driver')
    def test_close(self, mock_driver_class):
        mock_driver = MagicMock()
        mock_driver_class.return_value = mock_driver

        gs = GraphStore()
        gs.close()
        mock_driver.close.assert_called_once()
