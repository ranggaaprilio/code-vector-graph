// Shared shapes for the Graph Explorer's Svelte Flow view. The API speaks in
// `from`/`to` edges without coordinates; Svelte Flow wants `source`/`target`
// plus a `position` on every node. toFlow.ts and layout.ts bridge the two.
import type { Edge, Node } from '@xyflow/svelte';

/** What the Node Inspector and the custom node render. */
export type GraphNodeData = {
	id: string;
	label: string;
	caption: string;
	properties: Record<string, unknown>;
};

export type FlowNode = Node<GraphNodeData, 'graphNode'>;
export type FlowEdge = Edge;

/** Node as returned by /api/graph/subgraph (and synthesised by the page for
 *  /api/graph/nodes and Cypher results). */
export type ApiNode = {
	id: string;
	label: string;
	caption: string;
	properties: Record<string, unknown>;
};

/** Edge as returned by the API — `from`/`to` — or already in flow terms. */
export type ApiEdge = {
	id?: string;
	from?: string;
	to?: string;
	source?: string;
	target?: string;
	type?: string;
};

export type GraphElements = { nodes: FlowNode[]; edges: FlowEdge[] };

/** ELK `elk.direction` values the layout toggle exposes. */
export type LayoutDirection = 'DOWN' | 'RIGHT';

/** Actions a custom node can trigger on the page. Svelte Flow has no
 *  double-click node event, so the node component reads these from context. */
export type GraphActions = { expand: (id: string) => void };
export const GRAPH_ACTIONS_KEY = Symbol('graph-actions');
