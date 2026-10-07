// ELK layered layout for the Graph Explorer. Svelte Flow has no layout of its
// own and the API returns no coordinates, so every merge is followed by a full
// re-layout. elkjs is ~1.5MB, hence the dynamic import: the chunk is fetched
// the first time a layout actually runs on /graph, not on app load.
import { Position } from '@xyflow/svelte';
import type { ELK, ElkNode } from 'elkjs/lib/elk.bundled.js';
import type { FlowEdge, FlowNode, LayoutDirection } from './types';

/** Vertical distance between edge-label lanes (GraphFlowEdge.svelte). */
export const LABEL_LANE_STEP = 16;

/** Must match .graph-node in GraphFlowNode.svelte. */
export const NODE_WIDTH = 168;
export const NODE_HEIGHT = 40;

let elkPromise: Promise<ELK> | null = null;

function getElk(): Promise<ELK> {
	elkPromise ??= import('elkjs/lib/elk.bundled.js').then((m) => new m.default());
	return elkPromise;
}

export function handlePositions(direction: LayoutDirection): {
	sourcePosition: Position;
	targetPosition: Position;
} {
	return direction === 'RIGHT'
		? { sourcePosition: Position.Right, targetPosition: Position.Left }
		: { sourcePosition: Position.Bottom, targetPosition: Position.Top };
}

export function elkOptions(direction: LayoutDirection): Record<string, string> {
	return {
		'elk.algorithm': 'layered',
		'elk.direction': direction,
		'elk.edgeRouting': 'SPLINES',
		'elk.layered.spacing.nodeNodeBetweenLayers': '96',
		'elk.spacing.nodeNode': '40',
		'elk.spacing.componentComponent': '48',
		'elk.separateConnectedComponents': 'true'
	};
}

/** Returns a new node array with ELK positions and handle sides applied. */
export async function layoutWithElk(
	nodes: FlowNode[],
	edges: FlowEdge[],
	direction: LayoutDirection
): Promise<FlowNode[]> {
	if (nodes.length === 0) return nodes;
	const elk = await getElk();
	const graph: ElkNode = {
		id: 'root',
		layoutOptions: elkOptions(direction),
		children: nodes.map((n) => ({
			id: n.id,
			width: n.measured?.width ?? NODE_WIDTH,
			height: n.measured?.height ?? NODE_HEIGHT
		})),
		edges: edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] }))
	};
	const laid = await elk.layout(graph);
	const pos = new Map((laid.children ?? []).map((c) => [c.id, { x: c.x ?? 0, y: c.y ?? 0 }]));
	const sides = handlePositions(direction);
	return nodes.map((n) => ({ ...n, position: pos.get(n.id) ?? n.position, ...sides }));
}

/**
 * Spread edge labels over three lanes so siblings sharing a source (fan-out)
 * or a target (fan-in) do not stack their labels on one row. Rank each edge
 * among the edges of its source (ordered by target position) and among the
 * edges of its target (ordered by source position); the lane is the sum mod 3.
 * Pure: returns new edge objects, leaves the input untouched.
 */
export function assignLabelLanes(nodes: FlowNode[], edges: FlowEdge[]): FlowEdge[] {
	const pos = new Map(nodes.map((n) => [n.id, n.position]));
	const key = (id: string) => {
		const p = pos.get(id) ?? { x: 0, y: 0 };
		return p.x * 1e6 + p.y;
	};
	const rank = (group: (e: FlowEdge) => string, other: (e: FlowEdge) => string) => {
		const buckets = new Map<string, FlowEdge[]>();
		for (const e of edges) {
			const k = group(e);
			buckets.set(k, [...(buckets.get(k) ?? []), e]);
		}
		const out = new Map<string, number>();
		for (const list of buckets.values()) {
			list
				.slice()
				.sort((a, b) => key(other(a)) - key(other(b)))
				.forEach((e, i) => out.set(e.id, i));
		}
		return out;
	};
	const bySource = rank((e) => e.source, (e) => e.target);
	const byTarget = rank((e) => e.target, (e) => e.source);
	return edges.map((e) => ({
		...e,
		data: { ...(e.data ?? {}), lane: ((bySource.get(e.id) ?? 0) + (byTarget.get(e.id) ?? 0)) % 3 }
	}));
}
