<script lang="ts">
	// Bezier edge whose relationship label is nudged onto one of three vertical
	// "lanes" (data.lane, assigned by assignLabelLanes() after layout). Sibling
	// edges fanning out of one node otherwise put every label on the same row.
	import { BaseEdge, EdgeLabel, getBezierPath, type EdgeProps } from '@xyflow/svelte';
	import { LABEL_LANE_STEP } from './layout';

	let {
		id,
		sourceX,
		sourceY,
		targetX,
		targetY,
		sourcePosition,
		targetPosition,
		label,
		markerEnd,
		style,
		data
	}: EdgeProps = $props();

	const geometry = $derived(
		getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
	);
	const lane = $derived((data as { lane?: number } | undefined)?.lane ?? 0);
	const offsetY = $derived(((lane % 3) - 1) * LABEL_LANE_STEP);
</script>

<BaseEdge {id} path={geometry[0]} {markerEnd} {style} />
{#if label}
	<EdgeLabel x={geometry[1]} y={geometry[2] + offsetY}>{label}</EdgeLabel>
{/if}
