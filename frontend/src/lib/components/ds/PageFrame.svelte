<script lang="ts">
	import type { Snippet } from 'svelte';
	let { children }: { children?: Snippet } = $props();
</script>

<div class="page-frame">
	{@render children?.()}
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
		background: var(--color-canvas);
		min-height: 100dvh;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	@media (min-width: 769px) {
		.page-frame {
			height: 100dvh;
			min-height: 0;
		}
	}
</style>
