<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { appStore } from '$lib/stores/app.svelte';
	import { getCollection, getGraphStats, getChatConfig } from '$lib/api/client';
	import { topEntries } from '$lib/utils/format';
	import { tintForIndex, nodeStyle } from '$lib/utils/tints';
	import { SectionEyebrow, RibbonCard, Button, Skeleton } from '$lib/components/ds';

	type Collection = {
		collection?: string;
		points_count?: number;
		vector_size?: number;
		distance?: string;
		status?: string;
	};
	type GraphStats = {
		node_total?: number;
		rel_total?: number;
		labels?: Record<string, number>;
		rel_types?: Record<string, number>;
		scope?: string;
	};
	type ChatConfig = { provider?: string; model?: string; configured?: boolean; reason?: string };

	let collection = $state<Collection | null>(null);
	let graphStats = $state<GraphStats | null>(null);
	let chatConfig = $state<ChatConfig | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	const health = $derived(appStore.health);
	const appCount = $derived(appStore.apps.length);
	const repoCount = $derived(appStore.apps.reduce((n, a) => n + (a.repos?.length || 0), 0));

	const nodeLabels = $derived(topEntries(graphStats?.labels, 12));
	const relTypes = $derived(topEntries(graphStats?.rel_types, 10));
	const maxLabelCount = $derived(nodeLabels[0]?.[1] || 1);
	const maxRelCount = $derived(relTypes[0]?.[1] || 1);

	/** Card titles, also used as the loading placeholders so nothing shifts. */
	const STAT_CARDS = ['Indexed', 'System Status', 'Vector Collection', 'Graph Database'];

	function statusText(ok: boolean | null | undefined): string {
		return ok == null ? 'CHECKING…' : ok ? 'ONLINE' : 'DOWN';
	}

	function barPct(count: number, max: number): number {
		return max > 0 ? Math.round((count / max) * 100) : 0;
	}

	async function load() {
		loading = true;
		error = null;
		try {
			const [c, g, cc] = await Promise.all([
				getCollection(),
				getGraphStats(appStore.scopeParams()),
				getChatConfig()
			]);
			collection = c as Collection;
			graphStats = g as GraphStats;
			chatConfig = cc as ChatConfig;
		} catch (e) {
			error = String((e as Error)?.message || e);
		}
		loading = false;
	}

	onMount(load);

	// These figures are pure functions of the scope, so a scope change makes them
	// simply wrong. The old dashboard refetched via js/lib/lazy.js; that was lost
	// in the port and the numbers went stale until a manual Refresh.
	let seenScope = appStore.scopeVersion;
	$effect(() => {
		const v = appStore.scopeVersion;
		if (v === seenScope) return;
		seenScope = v;
		untrack(() => void load());
	});
</script>

<SectionEyebrow title="System" tint="steel" />

<div class="page-content">
	<p class="ds-caption scope-line">Scope: {appStore.scopeLabelText}</p>

	{#if error}
		<div class="error-banner ds-body-sm">{error}</div>
	{/if}

	<div class="stat-grid">
		{#if loading}
			{#each STAT_CARDS as title, i (title)}
				<RibbonCard {title} tint={tintForIndex(i)}>
					<Skeleton shape="block" width="100%" height="96px" />
				</RibbonCard>
			{/each}
		{:else}
			<RibbonCard title="Indexed" tint={tintForIndex(0)} interactive>
				<button class="card-link" onclick={() => goto('/apps')}>
					<div class="stat-row">
						<span>Applications</span>
						<span class="ds-mono ds-num">{appCount}</span>
					</div>
					<div class="stat-row">
						<span>Repositories</span>
						<span class="ds-mono ds-num">{repoCount}</span>
					</div>
				</button>
			</RibbonCard>

			<RibbonCard title="System Status" tint={tintForIndex(1)}>
				<div class="stat-row">
					<span>Qdrant</span>
					<span class="ds-mono ds-num">{statusText(health.qdrant?.ok)}</span>
				</div>
				<div class="stat-row">
					<span>Neo4j</span>
					<span class="ds-mono ds-num">{statusText(health.neo4j?.ok)}</span>
				</div>
				<div class="stat-row">
					<span>MCP Session</span>
					<span class="ds-mono ds-num">{statusText(health.mcp_session?.ok)}</span>
				</div>
				{#if chatConfig}
					<div class="stat-row">
						<span>Chat provider</span>
						<span class="ds-mono ds-num">{chatConfig.provider || '—'}</span>
					</div>
					<div class="stat-row">
						<span>Chat configured</span>
						<span class="ds-mono ds-num">{chatConfig.configured ? 'YES' : 'NO'}</span>
					</div>
					{#if !chatConfig.configured && chatConfig.reason}
						<p class="ds-caption reason">{chatConfig.reason}</p>
					{/if}
				{/if}
			</RibbonCard>

			<RibbonCard title="Vector Collection" tint={tintForIndex(2)}>
				{#if collection}
					<p class="ds-caption ds-mono collection-name">{collection.collection}</p>
					<div class="stat-row">
						<span>Points</span>
						<span class="ds-mono ds-num">{(collection.points_count || 0).toLocaleString()}</span>
					</div>
					<div class="stat-row">
						<span>Dimensions</span>
						<span class="ds-mono ds-num">{collection.vector_size}</span>
					</div>
					<div class="stat-row">
						<span>Distance</span>
						<span class="ds-mono ds-num">{collection.distance}</span>
					</div>
					<div class="stat-row">
						<span>Status</span>
						<span class="ds-mono ds-num">{collection.status}</span>
					</div>
				{:else}
					<p class="ds-body-sm">No collection found. Run the indexing pipeline first.</p>
				{/if}
			</RibbonCard>

			<RibbonCard title="Graph Database" tint={tintForIndex(3)}>
				{#if graphStats}
					<div class="stat-row">
						<span>Total Nodes</span>
						<span class="ds-mono ds-num">{(graphStats.node_total || 0).toLocaleString()}</span>
					</div>
					{#if graphStats.rel_total != null}
						<div class="stat-row">
							<span>Total Rels</span>
							<span class="ds-mono ds-num">{(graphStats.rel_total || 0).toLocaleString()}</span>
						</div>
					{/if}
					{#if graphStats.scope}
						<p class="ds-caption">{graphStats.scope}</p>
					{/if}
				{:else}
					<p class="ds-body-sm">No graph data available.</p>
				{/if}
			</RibbonCard>
		{/if}
	</div>

	{#if !loading && graphStats && nodeLabels.length}
		<div class="chart-grid">
			<RibbonCard title="Nodes by Label" tint="sky">
				<div class="bar-list">
					{#each nodeLabels as [label, count] (label)}
						<div class="bar-row">
							<span class="bar-label ds-body-sm">{label}</span>
							<div class="bar-track">
								<div
									class="bar-fill"
									style="width:{barPct(count, maxLabelCount)}%; background: var(--tint-{nodeStyle(
										label
									).tint})"
								></div>
							</div>
							<span class="bar-count ds-body-sm ds-mono">{count.toLocaleString()}</span>
						</div>
					{/each}
				</div>
			</RibbonCard>

			<RibbonCard title="Relationships by Type" tint="periwinkle">
				{#if relTypes.length}
					<div class="bar-list">
						{#each relTypes as [rel, count] (rel)}
							<div class="bar-row">
								<span class="bar-label ds-body-sm">{rel}</span>
								<div class="bar-track">
									<div
										class="bar-fill"
										style="width:{barPct(count, maxRelCount)}%; background: var(--tint-steel)"
									></div>
								</div>
								<span class="bar-count ds-body-sm ds-mono">{count.toLocaleString()}</span>
							</div>
						{/each}
					</div>
				{:else}
					<p class="ds-body-sm">Not available for a scoped application.</p>
				{/if}
			</RibbonCard>
		</div>
	{/if}

	<Button variant="secondary" class="refresh-btn" onclick={load}>↻ Refresh</Button>
</div>

<style>
	.page-content {
		padding: var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.scope-line {
		margin: 0;
	}

	.error-banner {
		border: var(--border-hairline);
		border-radius: var(--radius-md);
		padding: var(--space-sm) var(--space-md);
		color: var(--color-danger);
	}

	/* auto-fit reflows off the *container* width, so the grid is right whether the
	   rail is showing, collapsed, or the window is just narrow — no breakpoint
	   ladder to keep in sync. */
	.stat-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
		gap: var(--space-md);
	}

	.chart-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
		gap: var(--space-md);
	}

	.stat-row {
		display: flex;
		justify-content: space-between;
		gap: var(--space-sm);
		padding: var(--space-xxs) 0;
	}

	.reason {
		margin-top: var(--space-xs);
	}

	.collection-name {
		word-break: break-all;
		margin-bottom: var(--space-xs);
	}

	.card-link {
		display: block;
		width: 100%;
		background: transparent;
		border: none;
		padding: 0;
		margin: 0;
		font: inherit;
		color: inherit;
		text-align: left;
		cursor: pointer;
	}

	.bar-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.bar-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.bar-label {
		width: 108px;
		flex-shrink: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.bar-track {
		flex: 1;
		height: 10px;
		border: var(--border-hairline);
		border-radius: var(--radius-full);
		overflow: hidden;
		background: var(--color-canvas);
	}

	.bar-fill {
		height: 100%;
	}

	.bar-count {
		width: 48px;
		flex-shrink: 0;
		text-align: right;
	}

	:global(.refresh-btn) {
		align-self: flex-start;
	}
</style>
