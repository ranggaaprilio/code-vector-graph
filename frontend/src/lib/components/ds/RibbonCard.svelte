<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Tint } from '$lib/utils/tints';

	let {
		title,
		tint = 'sage',
		interactive = false,
		children,
		class: className = ''
	}: {
		title?: string;
		tint?: Tint;
		/** Adds hover/focus affordance. Set it whenever the card is clickable. */
		interactive?: boolean;
		children?: Snippet;
		class?: string;
	} = $props();
</script>

<div
	class="ribbon-card {className}"
	class:interactive
	style="--card-tint: var(--tint-{tint}); --card-tint-hover: var(--tint-{tint}-hover)"
>
	{#if title}
		<div class="ribbon-title ds-h3">{title}</div>
	{/if}
	<div class="ribbon-body">
		{@render children?.()}
	</div>
</div>

<style>
	.ribbon-card {
		border: var(--border-hairline);
		background: var(--color-canvas);
		height: 100%;
		display: flex;
		flex-direction: column;
	}

	.ribbon-title {
		background: var(--color-canvas);
		color: var(--color-ink);
		padding: var(--space-s) var(--space-md);
		border-bottom: var(--border-hairline);
	}

	.ribbon-body {
		background: var(--card-tint);
		padding: var(--space-md) var(--space-lg);
		color: var(--color-ink);
		flex: 1;
		transition: background-color var(--motion-base) var(--ease-snap);
	}

	/* The edge thickens via outline, not border, so nothing reflows on hover. */
	.interactive {
		transition: outline-color var(--motion-fast) var(--ease-snap);
		outline: var(--border-hairline-strong);
		outline-color: transparent;
		outline-offset: -1px;
	}

	.interactive:hover,
	.interactive:focus-within {
		outline-color: var(--color-frame-ink);
	}

	.interactive:hover .ribbon-body,
	.interactive:focus-within .ribbon-body {
		background: var(--card-tint-hover);
	}
</style>
