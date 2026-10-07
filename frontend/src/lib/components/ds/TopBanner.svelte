<script lang="ts">
	type Status = { label: string; ok: boolean | null };
	let { statuses = [] as Status[] }: { statuses?: Status[] } = $props();

	function stateOf(ok: boolean | null): 'up' | 'down' | 'unknown' {
		if (ok == null) return 'unknown';
		return ok ? 'up' : 'down';
	}

	function textOf(ok: boolean | null): string {
		if (ok == null) return 'Checking…';
		return ok ? 'Online' : 'Down';
	}
</script>

<header class="top-banner">
	<div class="brand">Enigram</div>
	<div class="statuses" role="status" aria-live="polite">
		{#each statuses as s (s.label)}
			<span class="status-item {stateOf(s.ok)}">
				<span class="dot" aria-hidden="true"></span>
				{s.label} · {textOf(s.ok)}
			</span>
		{/each}
	</div>
</header>

<style>
	.top-banner {
		background: var(--color-canvas);
		color: var(--color-ink);
		display: flex;
		align-items: center;
		justify-content: space-between;
		height: 64px;
		padding: 0 var(--space-lg);
		border-bottom: var(--border-hairline);
		flex-wrap: wrap;
		gap: var(--space-md);
	}

	.brand {
		font-family: var(--font-heading);
		font-size: var(--type-brand-size);
		font-weight: 600;
		letter-spacing: -0.01em;
	}

	.statuses {
		display: flex;
		gap: var(--space-lg);
		flex-wrap: wrap;
	}

	.status-item {
		display: inline-flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: var(--type-caption-size);
		font-weight: 500;
		white-space: nowrap;
	}

	.dot {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-full);
		background: currentColor;
		flex: none;
	}

	.status-item.up {
		color: var(--color-success);
	}

	.status-item.down {
		color: var(--color-danger);
	}

	.status-item.unknown {
		color: var(--color-ink-muted);
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
