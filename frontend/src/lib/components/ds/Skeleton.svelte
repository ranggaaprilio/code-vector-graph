<script lang="ts">
	let {
		width = '100%',
		height,
		shape = 'text'
	}: {
		width?: string;
		height?: string;
		/** Match the shape of what is loading so nothing shifts when it lands. */
		shape?: 'text' | 'block' | 'card';
	} = $props();

	const DEFAULT_HEIGHT = { text: '15px', block: '32px', card: '140px' } as const;
</script>

<span class="skeleton {shape}" style="width:{width}; height:{height ?? DEFAULT_HEIGHT[shape]}"
></span>

<style>
	.skeleton {
		display: block;
		background: var(--color-skeleton);
		border: var(--border-hairline);
		animation: skeleton-pulse 1.2s ease-in-out infinite;
	}

	.skeleton.text {
		display: inline-block;
	}

	@keyframes skeleton-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.45;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.skeleton {
			animation: none;
		}
	}
</style>
