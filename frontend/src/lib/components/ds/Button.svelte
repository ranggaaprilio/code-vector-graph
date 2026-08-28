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
		text-decoration: none;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-xs);
		padding: 10px 18px;
		border-radius: var(--radius-md);
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

	/* A slight physical press — the button dips a hair, nothing glows. */
	.ds-btn:not(:disabled):active {
		translate: 0 1px;
	}

	/* Hovering the page you are already on must not look like leaving it. */
	.ds-btn.is-current {
		cursor: default;
	}

	.ds-btn-primary {
		background: var(--color-primary);
		color: var(--color-on-primary);
		border: none;
	}

	.ds-btn-primary:not(:disabled):not(.is-current):hover {
		background: var(--color-primary-pressed);
	}

	.ds-btn-secondary {
		background: var(--color-canvas);
		color: var(--color-ink);
		border: 1px solid var(--color-hairline-strong);
	}

	.ds-btn-secondary:not(:disabled):not(.is-current):hover {
		background: var(--color-row-hover);
	}

	.ds-btn-secondary.is-current {
		background: var(--color-ink-deep);
		color: var(--color-canvas);
		border-color: var(--color-ink-deep);
	}

	.ds-btn-text-link {
		background: transparent;
		border: none;
		padding: 0;
		border-radius: 0;
		color: var(--color-link);
		text-decoration: underline;
		text-underline-offset: 2px;
		font-family: var(--font-body);
		font-size: var(--type-body-size);
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
