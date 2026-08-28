<script lang="ts">
	// The Svelte Flow surface. Lives one level below <SvelteFlowProvider> (see
	// routes/graph/+page.svelte) so useSvelteFlow() can hand fitView() back to
	// the page through the exported fit() function.
	import { setContext } from 'svelte';
	import {
		SvelteFlow,
		Background,
		BackgroundVariant,
		Controls,
		MiniMap,
		useSvelteFlow,
		type EdgeTypes,
		type Node,
		type NodeTypes
	} from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import './flow-theme.css';
	import GraphFlowNode from './GraphFlowNode.svelte';
	import GraphFlowEdge from './GraphFlowEdge.svelte';
	import { INK_HEX, nodeHex } from '$lib/utils/tints';
	import { GRAPH_ACTIONS_KEY, type FlowEdge, type FlowNode, type GraphNodeData } from './types';

	let {
		nodes = $bindable(),
		edges = $bindable(),
		onnodeclick,
		onexpand
	}: {
		nodes: FlowNode[];
		edges: FlowEdge[];
		onnodeclick: (data: GraphNodeData) => void;
		onexpand: (id: string) => void;
	} = $props();

	setContext(GRAPH_ACTIONS_KEY, { expand: (id: string) => onexpand(id) });

	const nodeTypes: NodeTypes = { graphNode: GraphFlowNode };
	const edgeTypes: EdgeTypes = { graphEdge: GraphFlowEdge };
	const { fitView } = useSvelteFlow();

	/** Fit every node into view. Duration mirrors --motion-slow. */
	export function fit(): Promise<boolean> {
		return fitView({ duration: 220, padding: 0.15 });
	}

	function minimapColor(node: Node): string {
		return nodeHex((node.data as GraphNodeData).label);
	}
</script>

<SvelteFlow
	bind:nodes
	bind:edges
	{nodeTypes}
	{edgeTypes}
	colorMode="light"
	fitView
	minZoom={0.2}
	maxZoom={2}
	nodesConnectable={false}
	deleteKey={null}
	defaultEdgeOptions={{ type: 'graphEdge' }}
	onnodeclick={({ node }) => onnodeclick(node.data)}
>
	<Background variant={BackgroundVariant.Lines} gap={24} />
	<Controls showLock={false} position="top-right" />
	<MiniMap nodeColor={minimapColor} nodeStrokeColor={INK_HEX} pannable zoomable />
</SvelteFlow>
