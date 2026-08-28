<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		tone = 'card',
		children
	}: {
		title?: string;
		/** `card` = framed rounded block; `bare` = a quiet inline line. */
		tone?: 'card' | 'bare';
		children?: Snippet;
	} = $props();
</script>

<div class="empty {tone}">
	{#if title}
		<p class="ds-h3 title">{title}</p>
	{/if}
	{#if children}
		<div class="body ds-prose">{@render children()}</div>
	{/if}
</div>

<style>
	.empty.card {
		background: var(--color-canvas);
		border: var(--border-hairline);
		border-radius: var(--radius-lg);
		padding: var(--space-xl);
	}

	.empty.bare {
		padding: var(--space-xl);
		text-align: center;
		color: var(--color-ink-muted);
	}

	.title {
		margin-bottom: var(--space-sm);
	}

	/* Inline code only — a <pre> block brings its own chrome. */
	.body :global(:not(pre) > code) {
		font-family: var(--font-mono);
		font-size: var(--type-body-sm-size);
		background: var(--color-row-zebra);
		border-radius: var(--radius-xs);
		padding: 1px 5px;
	}

	.body :global(p + p) {
		margin-top: var(--space-sm);
	}
</style>
