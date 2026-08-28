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
	const RADIUS = { text: 'var(--radius-xs)', block: 'var(--radius-md)', card: 'var(--radius-lg)' } as const;
</script>

<span
	class="skeleton {shape}"
	style="width:{width}; height:{height ?? DEFAULT_HEIGHT[shape]}; border-radius:{RADIUS[shape]}"
></span>

<style>
	.skeleton {
		display: block;
		background: var(--color-skeleton);
		background-image: linear-gradient(
			100deg,
			transparent 30%,
			rgb(255 255 255 / 0.6) 50%,
			transparent 70%
		);
		background-size: 200% 100%;
		background-position: 150% 0;
		animation: skeleton-shimmer 1.4s ease-in-out infinite;
	}

	.skeleton.text {
		display: inline-block;
	}

	@keyframes skeleton-shimmer {
		to {
			background-position: -50% 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.skeleton {
			animation: none;
		}
	}
</style>
