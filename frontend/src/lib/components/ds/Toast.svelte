<script lang="ts">
	import { fly } from 'svelte/transition';
	import { MediaQuery } from 'svelte/reactivity';

	let { message = '', onDismiss }: { message?: string; onDismiss?: () => void } = $props();

	const reduced = new MediaQuery('(prefers-reduced-motion: reduce)');
	const duration = $derived(reduced.current ? 0 : 160);
</script>

{#if message}
	<div class="toast-slot" role="status" aria-live="polite">
		<button
			type="button"
			class="toast ds-body-sm"
			onclick={onDismiss}
			transition:fly={{ y: 8, duration }}
		>
			{message}
		</button>
	</div>
{/if}

<style>
	.toast-slot {
		position: fixed;
		bottom: var(--space-xl);
		left: 50%;
		transform: translateX(-50%);
		z-index: 50;
	}

	.toast {
		background: var(--color-canvas);
		border: var(--border-hairline);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-modal);
		padding: var(--space-sm) var(--space-lg);
		cursor: pointer;
		font-family: var(--font-body);
		color: var(--color-ink);
		transition:
			background-color var(--motion-fast) var(--ease-snap),
			box-shadow var(--motion-fast) var(--ease-snap);
	}

	.toast:hover {
		background: var(--color-row-hover);
	}

	.toast:active {
		box-shadow: var(--shadow-card);
	}
</style>
