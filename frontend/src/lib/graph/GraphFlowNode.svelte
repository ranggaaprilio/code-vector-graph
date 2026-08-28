<script lang="ts">
	// One Neo4j node as a catalog card: tint fill inside a hairline, with the
	// same .ds-swatch glyph the legend and inspector use, so a node and its
	// legend entry read as the same thing. Shape carries the label so the view
	// never relies on colour alone.
	import { getContext } from 'svelte';
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';
	import { nodeShape, nodeTintVar } from '$lib/utils/tints';
	import { GRAPH_ACTIONS_KEY, type FlowNode, type GraphActions } from './types';

	let {
		data,
		selected,
		sourcePosition = Position.Bottom,
		targetPosition = Position.Top
	}: NodeProps<FlowNode> = $props();

	const actions = getContext<GraphActions | undefined>(GRAPH_ACTIONS_KEY);
</script>

<!-- Svelte Flow's wrapper already provides the focusable, keyboard-reachable
     node; double-click is a pointer shortcut for the inspector's Expand button. -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="graph-node"
	class:selected
	data-label={data.label}
	title="{data.label}: {data.caption}"
	style:--node-tint={nodeTintVar(data.label)}
	ondblclick={() => actions?.expand(data.id)}
>
	<Handle type="target" position={targetPosition} isConnectable={false} />
	<span class="ds-swatch glyph" data-shape={nodeShape(data.label)}></span>
	<span class="caption">{data.caption}</span>
	<Handle type="source" position={sourcePosition} isConnectable={false} />
</div>

<style>
	.graph-node {
		/* Keep in sync with NODE_WIDTH / NODE_HEIGHT in layout.ts. */
		width: 168px;
		height: 40px;
		box-sizing: border-box;
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		padding: 0 var(--space-sm);
		background: var(--node-tint);
		border: var(--border-hairline);
		border-radius: var(--radius-sm);
		color: var(--color-ink);
		font-family: var(--font-heading);
		font-size: 11px;
		line-height: 1.2;
		cursor: pointer;
		transition: box-shadow var(--motion-base) var(--ease-snap);
	}

	/* Selection lifts with a soft ring + shadow instead of the old hard
	   bevel. */
	.graph-node.selected {
		border: 1px solid var(--color-primary);
		box-shadow: 0 0 0 2px color-mix(in oklab, var(--color-primary) 25%, transparent),
			var(--shadow-card);
	}

	.glyph {
		background: var(--color-ink-deep);
	}

	.caption {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
