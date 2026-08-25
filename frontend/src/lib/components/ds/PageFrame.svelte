<script lang="ts">
	import type { Snippet } from 'svelte';
	let { children }: { children?: Snippet } = $props();
</script>

<div class="page-frame">
	<div class="page-inner">
		{@render children?.()}
	</div>
</div>

<style>
	/* Two layout modes, on purpose.
	   Narrow: the frame grows and the *page* scrolls — a phone has no room to
	   give a rail and an inner scroll pane at once.
	   Wide: the frame is exactly one viewport tall, which gives every
	   full-height view below it (chat's composer, the graph canvas, the files
	   explorer panes) a definite height to resolve `height: 100%` against. With
	   only a min-height that chain fell back to `auto` and those views grew past
	   the viewport instead of scrolling inside it — which pushed chat's composer
	   off-screen entirely. */
	.page-frame {
		background: var(--color-frame-ink);
		padding: var(--frame-width-mobile);
		min-height: 100dvh;
	}

	.page-inner {
		background: var(--color-canvas);
		min-height: calc(100dvh - 2 * var(--frame-width-mobile));
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	@media (min-width: 481px) {
		.page-frame {
			padding: var(--frame-width-tablet);
		}
		.page-inner {
			min-height: calc(100dvh - 2 * var(--frame-width-tablet));
		}
	}

	@media (min-width: 769px) {
		.page-frame {
			padding: var(--frame-width);
			height: 100dvh;
		}
		.page-inner {
			height: 100%;
			min-height: 0;
		}
	}
</style>
