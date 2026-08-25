<script lang="ts">
	type Status = { label: string; ok: boolean | null };
	let { statuses = [] as Status[] }: { statuses?: Status[] } = $props();

	function stateOf(ok: boolean | null): 'up' | 'down' | 'unknown' {
		if (ok == null) return 'unknown';
		return ok ? 'up' : 'down';
	}

	function textOf(ok: boolean | null): string {
		if (ok == null) return 'CHECKING…';
		return ok ? 'ONLINE' : 'DOWN';
	}
</script>

<header class="top-banner">
	<div class="brand ds-display">Code Vector Graph</div>
	<!-- Design.md's phone-callout slot: the thing the page wants you to notice.
	     Dell red is spent on DOWN only, never on the healthy state. -->
	<div class="statuses" role="status" aria-live="polite">
		{#each statuses as s (s.label)}
			<span class="status-item {stateOf(s.ok)}">
				<span class="dot" aria-hidden="true"></span>
				{s.label}: {textOf(s.ok)}
			</span>
		{/each}
	</div>
</header>

<style>
	.top-banner {
		background: var(--color-frame-ink);
		color: var(--color-canvas);
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-md) var(--space-lg);
		flex-wrap: wrap;
		gap: var(--space-md);
	}

	.brand {
		font-size: var(--type-brand-size);
	}

	.statuses {
		display: flex;
		gap: var(--space-lg);
		flex-wrap: wrap;
	}

	.status-item {
		display: inline-flex;
		align-items: center;
		gap: var(--space-s);
		font-family: var(--font-heading);
		font-weight: 700;
		font-size: var(--type-h2-size);
		white-space: nowrap;
	}

	.dot {
		width: 8px;
		height: 8px;
		background: currentColor;
		flex: none;
	}

	.status-item.up {
		color: var(--color-canvas);
	}

	.status-item.down {
		color: var(--color-primary);
	}

	.status-item.unknown {
		color: var(--color-on-ink-muted);
	}

	.status-item.unknown .dot {
		animation: status-pulse 1.4s ease-in-out infinite;
	}

	@keyframes status-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.3;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.status-item.unknown .dot {
			animation: none;
		}
	}
</style>
