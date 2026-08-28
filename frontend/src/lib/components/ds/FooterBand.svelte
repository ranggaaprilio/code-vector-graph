<script lang="ts">
	import type { Snippet } from 'svelte';
	let { children }: { children?: Snippet } = $props();
</script>

<footer class="footer-band ds-body-sm">
	{@render children?.()}
</footer>

<style>
	.footer-band {
		background: var(--color-canvas);
		border-top: var(--border-hairline);
		padding: var(--space-md) var(--space-lg);
		color: var(--color-ink-muted);
	}
</style>
