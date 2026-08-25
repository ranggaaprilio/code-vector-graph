<script lang="ts">
	import type { Snippet } from 'svelte';
	let { children }: { children?: Snippet } = $props();
</script>

<div class="cta">
	{@render children?.()}
</div>

<style>
	.cta {
		background: var(--color-primary);
		color: var(--color-on-primary);
		border: var(--border-hairline);
		padding: var(--space-lg);
		font-size: var(--type-body-size);
	}

	.cta :global(a) {
		color: var(--color-on-primary);
	}
</style>
