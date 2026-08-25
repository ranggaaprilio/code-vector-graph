<script lang="ts">
	import type { Snippet } from 'svelte';

	type Variant = 'primary' | 'secondary' | 'text-link';

	let {
		variant = 'primary',
		href,
		loading = false,
		current = false,
		children,
		class: className = '',
		...rest
	}: {
		variant?: Variant;
		href?: string;
		loading?: boolean;
		/** This button/link represents where you already are: no hover invert. */
		current?: boolean;
		children?: Snippet;
		class?: string;
		[key: string]: unknown;
	} = $props();
</script>

{#if href}
	<a
		{href}
		class="ds-btn ds-btn-{variant} {className}"
		class:is-current={current}
		aria-current={current ? 'page' : undefined}
		{...rest}
	>
		{@render children?.()}
	</a>
{:else}
	<button
		class="ds-btn ds-btn-{variant} {className}"
		class:is-current={current}
		aria-busy={loading || undefined}
		{...rest}
	>
		{@render children?.()}
	</button>
{/if}

<style>
	.ds-btn {
		font-family: var(--font-heading);
		font-size: var(--type-button-size);
		font-weight: var(--type-button-weight);
		text-transform: uppercase;
		text-decoration: none;
		display: inline-block;
		padding: var(--space-s) var(--space-lg);
		border-radius: var(--radius-none);
		cursor: pointer;
		transition:
			background-color var(--motion-fast) var(--ease-snap),
			color var(--motion-fast) var(--ease-snap),
			border-color var(--motion-fast) var(--ease-snap),
			translate var(--motion-fast) var(--ease-snap);
	}

	.ds-btn:disabled,
	.ds-btn[aria-busy='true'] {
		cursor: not-allowed;
		opacity: 0.5;
	}

	/* Mechanical press — the button moves, nothing glows. */
	.ds-btn:not(:disabled):active {
		translate: 1px 1px;
	}

	/* Hover inverts ink/canvas. No new colour enters the palette. */
	.ds-btn-primary {
		background: var(--color-frame-ink);
		color: var(--color-on-primary);
		border: var(--border-hairline);
	}

	/* Hovering the page you are already on must not look like leaving it. */
	.ds-btn.is-current {
		cursor: default;
	}

	.ds-btn-primary:not(:disabled):not(.is-current):hover {
		background: var(--color-canvas);
		color: var(--color-ink);
	}

	.ds-btn-secondary {
		background: var(--color-canvas);
		color: var(--color-ink);
		border: var(--border-hairline);
	}

	.ds-btn-secondary:not(:disabled):not(.is-current):hover {
		background: var(--color-frame-ink);
		color: var(--color-canvas);
	}

	.ds-btn-text-link {
		background: transparent;
		border: none;
		padding: 0;
		color: var(--color-link);
		text-decoration: underline;
		text-underline-offset: 2px;
		font-family: var(--font-body);
		font-size: var(--type-body-size);
		text-transform: none;
		font-weight: 400;
		transition: text-decoration-thickness var(--motion-fast) var(--ease-snap);
	}

	.ds-btn-text-link:not(:disabled):hover {
		text-decoration-thickness: 2px;
	}

	.ds-btn-text-link:not(:disabled):active {
		translate: 0;
	}
</style>
