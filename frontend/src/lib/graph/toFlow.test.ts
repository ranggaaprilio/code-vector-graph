import { describe, it, expect } from 'vitest';
import {
	edgeId,
	elementsFromCypherRows,
	makeFlowNode,
	mergeGraph,
	nodesFromLabelResponse
} from './toFlow';
import type { ApiNode, GraphElements } from './types';

const api = (id: string, label = 'Function'): ApiNode => ({
	id,
	label,
	caption: id,
	properties: { name: id }
});

const empty: GraphElements = { nodes: [], edges: [] };

describe('mergeGraph', () => {
	it('adds nodes as graphNode flow nodes with placeholder positions', () => {
		const r = mergeGraph(empty, [api('a'), api('b', 'Class')], []);
		expect(r.addedNodes).toBe(2);
		expect(r.nodes.map((n) => n.id)).toEqual(['a', 'b']);
		expect(r.nodes[0].type).toBe('graphNode');
		expect(r.nodes[0].position).toEqual({ x: 0, y: 0 });
		expect(r.nodes[1].data.label).toBe('Class');
	});

	it('dedupes nodes by id across batches and skips blank ids', () => {
		const first = mergeGraph(empty, [api('a')], []);
		const r = mergeGraph(first, [api('a'), api(''), api('b')], []);
		expect(r.nodes.map((n) => n.id)).toEqual(['a', 'b']);
		expect(r.addedNodes).toBe(1);
	});

	it('maps API from/to onto source/target and synthesises a stable edge id', () => {
		const r = mergeGraph(empty, [api('a'), api('b')], [{ from: 'a', to: 'b', type: 'CALLS' }]);
		expect(r.addedEdges).toBe(1);
		expect(r.edges[0]).toMatchObject({
			id: edgeId('a', 'b', 'CALLS'),
			source: 'a',
			target: 'b',
			type: 'graphEdge',
			label: 'CALLS'
		});
		expect(r.edges[0].markerEnd).toBeTruthy();
	});

	it('accepts edges already expressed as source/target', () => {
		const r = mergeGraph(empty, [api('a'), api('b')], [{ id: 'e1', source: 'a', target: 'b' }]);
		expect(r.edges).toHaveLength(1);
		expect(r.edges[0].id).toBe('e1');
		expect(r.edges[0].label).toBeUndefined();
	});

	it('drops edges whose endpoints are missing, even when only one side exists', () => {
		const r = mergeGraph(
			empty,
			[api('a')],
			[
				{ from: 'a', to: 'ghost', type: 'CALLS' },
				{ from: 'ghost', to: 'a', type: 'CALLS' }
			]
		);
		expect(r.edges).toHaveLength(0);
		expect(r.addedEdges).toBe(0);
	});

	it('accepts an edge whose endpoint arrives in the same batch or already exists', () => {
		const first = mergeGraph(empty, [api('a')], []);
		const r = mergeGraph(first, [api('b')], [{ from: 'a', to: 'b', type: 'CONTAINS' }]);
		expect(r.edges).toHaveLength(1);
	});

	it('folds parallel relationships between the same pair into one labelled edge', () => {
		const first = mergeGraph(empty, [api('a'), api('b')], [{ from: 'a', to: 'b', type: 'CONTAINS' }]);
		const r = mergeGraph(first, [], [
			{ from: 'a', to: 'b', type: 'DEFINES' },
			{ from: 'b', to: 'a', type: 'CALLS' }
		]);
		expect(r.addedEdges).toBe(2);
		// a->b drawn once with both types; b->a is a different direction, so its own edge.
		expect(r.edges).toHaveLength(2);
		expect(r.edges[0].label).toBe('CONTAINS · DEFINES');
		expect(r.edges[0].data).toMatchObject({ types: ['CONTAINS', 'DEFINES'] });
		expect(r.edges[1]).toMatchObject({ source: 'b', target: 'a', label: 'CALLS' });
	});

	it('does not duplicate an edge that is merged twice', () => {
		const first = mergeGraph(empty, [api('a'), api('b')], [{ from: 'a', to: 'b', type: 'CALLS' }]);
		const r = mergeGraph(first, [], [{ from: 'a', to: 'b', type: 'CALLS' }]);
		expect(r.edges).toHaveLength(1);
		expect(r.addedEdges).toBe(0);
	});

	it('does not mutate the previous graph', () => {
		const first = mergeGraph(empty, [api('a')], []);
		const snapshot = JSON.stringify(first);
		mergeGraph(first, [api('b')], [{ from: 'a', to: 'b' }]);
		expect(JSON.stringify(first)).toBe(snapshot);
	});
});

describe('makeFlowNode', () => {
	it('is neither connectable nor deletable — the explorer is read-only', () => {
		const n = makeFlowNode(api('a'));
		expect(n.connectable).toBe(false);
		expect(n.deletable).toBe(false);
	});
});

describe('nodesFromLabelResponse', () => {
	it('captions by name, then path, then a truncated id', () => {
		const out = nodesFromLabelResponse('File', [
			{ id: 'id-1', properties: { name: 'main.py', path: '/x/main.py' } },
			{ id: 'id-2', properties: { path: '/x/util.py' } },
			{ id: 'abcdefghijklmnopqrstuvwxyz', properties: {} }
		]);
		expect(out.map((n) => n.caption)).toEqual(['main.py', '/x/util.py', 'abcdefghijkl']);
		expect(out.every((n) => n.label === 'File')).toBe(true);
	});
});

describe('elementsFromCypherRows', () => {
	it('extracts nodes (first label wins) and relationships from tagged cells', () => {
		const rows = [
			{
				n: { _type: 'node', _labels: ['Function', 'Chunk'], id: 'f1', name: 'run' },
				r: { _type: 'relationship', _element_id: 'r1', _rel_type: 'CALLS', start_node_id: 'f1', end_node_id: 'f2' },
				count: 3
			},
			{ n: { _type: 'node', _labels: [], _element_id: 'el-2' }, r: null, count: 1 }
		];
		const { nodes, edges } = elementsFromCypherRows(rows);
		expect(nodes).toHaveLength(2);
		expect(nodes[0]).toMatchObject({ id: 'f1', label: 'Function', caption: 'run' });
		expect(nodes[1]).toMatchObject({ id: 'el-2', label: 'Node' });
		expect(edges).toEqual([{ id: 'r1', from: 'f1', to: 'f2', type: 'CALLS' }]);
	});
});
