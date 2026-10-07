// Pure mapping from API payloads to Svelte Flow elements. No DOM, no Svelte —
// so it runs in the node-environment Vitest project.
import { MarkerType } from '@xyflow/svelte';
import { INK_HEX } from '../utils/tints';
import type { ApiEdge, ApiNode, FlowEdge, FlowNode, GraphElements } from './types';

export type MergeResult = GraphElements & { addedNodes: number; addedEdges: number };

export function edgeId(source: string, target: string, type?: string): string {
	return `${source}->${type || 'REL'}->${target}`;
}

export function makeFlowNode(n: ApiNode): FlowNode {
	return {
		id: n.id,
		type: 'graphNode',
		// Placeholder — layoutWithElk() overwrites it before anything is drawn.
		position: { x: 0, y: 0 },
		data: { id: n.id, label: n.label, caption: n.caption, properties: n.properties ?? {} },
		connectable: false,
		deletable: false
	};
}

export function makeFlowEdge(id: string, source: string, target: string, type?: string): FlowEdge {
	return {
		id,
		source,
		target,
		type: 'graphEdge',
		label: type,
		data: { types: type ? [type] : [] },
		// SVG markers take a literal colour, not a var() reference.
		markerEnd: { type: MarkerType.ArrowClosed, color: INK_HEX, width: 16, height: 16 },
		selectable: false,
		deletable: false
	};
}

/** Relationship types carried by one drawn edge, in arrival order. */
function edgeTypes(e: FlowEdge): string[] {
	return ((e.data as { types?: string[] } | undefined)?.types ?? []).slice();
}

/**
 * Merge nodes/edges into an existing graph. Nodes are deduped by id. Edges are
 * only added once both endpoints exist (counting nodes added in this same
 * batch) and are mapped from the API's from/to to Svelte Flow's source/target.
 *
 * Parallel relationships (same source → same target, e.g. CONTAINS + DEFINES)
 * are drawn as ONE edge whose label lists every type: Svelte Flow routes both
 * through the same handles, so two edges would sit exactly on top of each
 * other and their labels would collide. `addedEdges` still counts every
 * relationship absorbed, matching the API's numbers.
 */
export function mergeGraph(prev: GraphElements, nodes: ApiNode[], edges: ApiEdge[]): MergeResult {
	const ids = new Set(prev.nodes.map((n) => n.id));
	const edgeIds = new Set(prev.edges.map((e) => e.id));
	const outNodes = [...prev.nodes];
	const outEdges = [...prev.edges];
	const byPair = new Map(outEdges.map((e, i) => [`${e.source}\u0000${e.target}`, i]));
	let addedNodes = 0;
	let addedEdges = 0;

	for (const n of nodes ?? []) {
		if (!n?.id || ids.has(n.id)) continue;
		ids.add(n.id);
		outNodes.push(makeFlowNode(n));
		addedNodes++;
	}
	for (const e of edges ?? []) {
		if (!e) continue;
		const source = e.from ?? e.source ?? '';
		const target = e.to ?? e.target ?? '';
		const id = e.id || edgeId(source, target, e.type);
		if (edgeIds.has(id) || !ids.has(source) || !ids.has(target)) continue;
		edgeIds.add(id);
		addedEdges++;

		const pairKey = `${source}\u0000${target}`;
		const existingIdx = byPair.get(pairKey);
		if (existingIdx === undefined) {
			byPair.set(pairKey, outEdges.length);
			outEdges.push(makeFlowEdge(id, source, target, e.type));
			continue;
		}
		const existing = outEdges[existingIdx];
		const types = edgeTypes(existing);
		if (e.type && !types.includes(e.type)) {
			types.push(e.type);
			outEdges[existingIdx] = { ...existing, label: types.join(' · '), data: { types } };
		}
	}
	return { nodes: outNodes, edges: outEdges, addedNodes, addedEdges };
}

/** /api/graph/nodes returns flat properties without label/caption; add them. */
export function nodesFromLabelResponse(
	label: string,
	apiNodes: { id: string; properties: Record<string, unknown> }[]
): ApiNode[] {
	return apiNodes.map((n) => ({
		id: n.id,
		label,
		caption: String(n.properties.name || n.properties.path || n.id.slice(0, 12)),
		properties: n.properties
	}));
}

/** Pull nodes/relationships out of /api/graph/cypher rows (cells tagged with
 *  `_type: 'node' | 'relationship'`). */
export function elementsFromCypherRows(rows: Record<string, unknown>[]): {
	nodes: ApiNode[];
	edges: ApiEdge[];
} {
	const nodes: ApiNode[] = [];
	const edges: ApiEdge[] = [];
	for (const row of rows) {
		for (const val of Object.values(row)) {
			if (!val || typeof val !== 'object') continue;
			const obj = val as Record<string, unknown>;
			if (obj._type === 'node') {
				const labels = obj._labels as string[] | undefined;
				const label = labels?.[0] || 'Node';
				const id = String(obj.id || obj._element_id || '');
				nodes.push({
					id,
					label,
					caption: String(obj.name || obj.path || id.slice(0, 12)),
					properties: obj
				});
			} else if (obj._type === 'relationship') {
				edges.push({
					id: String(obj._element_id || ''),
					from: String(obj.start_node_id || ''),
					to: String(obj.end_node_id || ''),
					type: obj._rel_type as string | undefined
				});
			}
		}
	}
	return { nodes, edges };
}
