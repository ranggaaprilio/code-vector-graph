<script lang="ts">
	import type { Tint } from '$lib/utils/tints';

	let {
		title,
		tint = 'olive',
		sticky = false
	}: {
		title: string;
		tint?: Tint;
		/** Keeps the page title in view on long scrolling views. Stays flat. */
		sticky?: boolean;
	} = $props();
</script>

<div class="eyebrow" class:sticky style="--eyebrow-tint: var(--tint-{tint})">
	<h1 class="ds-display">{title}</h1>
</div>

<style>
	.eyebrow {
		background: var(--eyebrow-tint);
		padding: var(--space-xxl) var(--space-lg);
		color: var(--color-ink);
		border-bottom: var(--border-hairline);
	}

	.sticky {
		position: sticky;
		top: 0;
		z-index: 20;
	}
</style>
