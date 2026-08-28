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

<div class="eyebrow" class:sticky>
	<span class="accent" style="background: var(--tint-{tint})" aria-hidden="true"></span>
	<h1 class="ds-h1">{title}</h1>
</div>

<style>
	.eyebrow {
		background: var(--color-canvas);
		display: flex;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-lg) var(--space-lg);
		border-bottom: var(--border-hairline);
	}

	.accent {
		width: 4px;
		height: 28px;
		border-radius: var(--radius-full);
		flex-shrink: 0;
	}

	.sticky {
		position: sticky;
		top: 0;
		z-index: 20;
	}
</style>
