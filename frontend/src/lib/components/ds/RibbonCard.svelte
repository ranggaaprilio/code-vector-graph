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
		/** Adds hover/focus lift. Set it whenever the card is clickable. */
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
		border-radius: var(--radius-lg);
		background: var(--color-canvas);
		overflow: hidden;
		height: 100%;
		display: flex;
		flex-direction: column;
		transition:
			box-shadow var(--motion-base) var(--ease-snap),
			transform var(--motion-base) var(--ease-snap);
	}

	.ribbon-title {
		background: var(--color-canvas);
		color: var(--color-ink);
		padding: var(--space-sm) var(--space-lg);
		border-bottom: var(--border-hairline);
	}

	.ribbon-body {
		background: var(--card-tint);
		padding: var(--space-md) var(--space-lg);
		color: var(--color-ink);
		flex: 1;
		transition: background-color var(--motion-base) var(--ease-snap);
	}

	.interactive {
		cursor: pointer;
	}

	.interactive:hover,
	.interactive:focus-within {
		box-shadow: var(--shadow-card);
		transform: translateY(-1px);
	}

	.interactive:hover .ribbon-body,
	.interactive:focus-within .ribbon-body {
		background: var(--card-tint-hover);
	}

	@media (prefers-reduced-motion: reduce) {
		.interactive:hover,
		.interactive:focus-within {
			transform: none;
		}
	}
</style>
