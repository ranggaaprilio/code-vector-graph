<script lang="ts">
	// Applications list (#/apps) — one card per indexed application.
	// Ported from the old vanilla-JS view at
	// api/static/views/apps.html + api/static/js/views/apps.js.
	import { goto } from '$app/navigation';
	import { appStore } from '$lib/stores/app.svelte';
	import {
		SectionEyebrow,
		RibbonCard,
		CtaBlockRed,
		Button,
		TextInput,
		Badge,
		Skeleton,
		EmptyState
	} from '$lib/components/ds';
	import { tintForIndex, tintForLabel } from '$lib/utils/tints';
	import { langEntries } from '$lib/utils/format';

	interface Repo {
		name: string;
		root: string;
		app: string;
		source: 'recorded' | 'derived';
		file_count: number;
		chunk_count: number;
		languages: Record<string, number>;
		has_wiki: boolean;
		wiki_pages: number;
		indexed_at: string | null;
	}

	interface App {
		name: string;
		repos: Repo[];
		file_count: number;
		chunk_count: number;
		languages: Record<string, number>;
		has_wiki: boolean;
		wiki_pages: number;
		source: 'recorded' | 'derived';
	}

	let filter = $state('');
	let refreshing = $state(false);

	// appStore.apps is typed loosely (format.ts's minimal AppInfo) — the API
	// actually returns the richer shape above.
	const apps = $derived((appStore.apps as unknown as App[]) ?? []);

	const loading = $derived(!appStore.appsLoaded && !appStore.appsError && !refreshing);

	const filtered = $derived.by(() => {
		const q = filter.trim().toLowerCase();
		const matches = q
			? apps.filter(
					(a) =>
						(a.name || '').toLowerCase().includes(q) ||
						(a.repos || []).some((r) => (r.name || '').toLowerCase().includes(q))
				)
			: apps;
		// langBar() used to be evaluated four times per card straight from the
		// template; hoisting it here computes each card's view model once.
		return matches.map((app, i) => ({
			app,
			tint: tintForIndex(i),
			langs: langBar(app)
		}));
	});

	async function refresh() {
		refreshing = true;
		try {
			await appStore.loadApps(true);
		} finally {
			refreshing = false;
		}
	}

	function open(app: App) {
		if (!app?.name) return;
		appStore.setScope(app.name);
		goto(`/apps/${encodeURIComponent(app.name)}/overview`);
	}

	function openRepo(app: App, repo: Repo, e: MouseEvent) {
		e.stopPropagation();
		if (!app?.name || !repo?.name) return;
		appStore.setScope(app.name, repo.name);
		const q = new URLSearchParams({ repo: repo.name });
		goto(`/apps/${encodeURIComponent(app.name)}/files?${q}`);
	}

	function onCardKeydown(e: KeyboardEvent, app: App) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			open(app);
		}
	}

	function isDerived(app: App): boolean {
		return app.source === 'derived' || (app.repos || []).some((r) => r.source === 'derived');
	}

	function fmt(n: number | undefined): string {
		return Number(n || 0).toLocaleString();
	}

	/** [{lang, count, pct, tint}] for the stacked language bar. */
	function langBar(app: App) {
		const entries = langEntries(app.languages);
		const total = entries.reduce((s, [, c]) => s + (c || 0), 0);
		return entries.map(([lang, count]) => ({
			lang,
			count,
			pct: total
				? Math.max(2, Math.round((count / total) * 100))
				: Math.round(100 / (entries.length || 1)),
			tint: tintForLabel(lang)
		}));
	}
</script>

<SectionEyebrow title="Applications" tint="olive" />

<div class="toolbar">
	<span class="ds-caption count">{filtered.length} of {apps.length} applications</span>
	<div class="spacer"></div>
	<div class="filter-wrap">
		<TextInput bind:value={filter} placeholder="Filter applications or repos…" />
	</div>
	<Button variant="secondary" onclick={refresh} disabled={refreshing}>
		{refreshing ? 'Refreshing…' : '↻ Refresh'}
	</Button>
</div>

<div class="content">
	{#if appStore.appsError}
		<div class="error-banner ds-body-sm">
			{appStore.appsError}
			<button type="button" class="retry-link" onclick={refresh}>retry</button>
		</div>
	{/if}

	{#if loading}
		<div class="grid">
			{#each [0, 1, 2] as i (i)}
				<div class="skeleton-card">
					<Skeleton height="18px" width="60%" />
					<Skeleton height="12px" width="40%" />
					<Skeleton height="20px" width="90%" />
					<Skeleton height="6px" width="100%" />
				</div>
			{/each}
		</div>
	{:else if !apps.length}
		<div class="empty-wrap">
			<EmptyState title="No indexed applications found.">
				<p>Index a repository first:</p>
				<pre class="code-block ds-mono ds-body-sm"><code
						>cvg-ingest --repo-path /path/to/repo</code
					></pre>
				<p>
					Set <code>CVG_REPOS_ROOT</code> (e.g. your <code>~/Repository</code> folder) to group
					several repositories under one application, or use <code>CVG_APP_MAP</code> for an
					explicit grouping.
				</p>
			</EmptyState>
		</div>
	{:else if !filtered.length}
		<EmptyState tone="bare">
			<p>No application matches &ldquo;{filter}&rdquo;.</p>
		</EmptyState>
	{:else}
		<div class="grid">
			{#each filtered as { app, tint, langs } (app.name)}
				<div
					class="card"
					role="button"
					tabindex="0"
					onclick={() => open(app)}
					onkeydown={(e) => onCardKeydown(e, app)}
				>
					<RibbonCard title={app.name} {tint} interactive>
						<div class="card-body">
							<div class="card-head">
								<span class="ds-caption repo-count">
									{(app.repos || []).length} repositor{(app.repos || []).length === 1
										? 'y'
										: 'ies'}
								</span>
								<div class="badges">
									{#if app.has_wiki}
										<Badge label="wiki" />
									{/if}
									{#if isDerived(app)}
										<span
											class="derived-tag ds-caption"
											title="Grouped from file paths; run cvg-backfill-repo to record it"
										>
											derived
										</span>
									{/if}
								</div>
							</div>

							{#if (app.repos || []).length}
								<div class="repo-chips">
									{#each app.repos as r (r.name)}
										<button
											type="button"
											class="repo-chip ds-mono ds-caption"
											title={r.root}
											onclick={(e) => openRepo(app, r, e)}
										>
											{r.name}
										</button>
									{/each}
								</div>
							{/if}

							<div class="counts">
								<div>
									<div class="ds-caption">Files</div>
									<div class="ds-mono ds-num count-value">{fmt(app.file_count)}</div>
								</div>
								<div>
									<div class="ds-caption">Chunks</div>
									<div class="ds-mono ds-num count-value">{fmt(app.chunk_count)}</div>
								</div>
							</div>

							{#if langs.length}
								<div class="lang-bar-wrap">
									<div class="lang-bar">
										{#each langs as l (l.lang)}
											<div
												class="lang-seg"
												style="width:{l.pct}%; background: var(--tint-{l.tint})"
												title="{l.lang}: {fmt(l.count)}"
											></div>
										{/each}
									</div>
									<div class="lang-legend">
										{#each langs.slice(0, 4) as l (l.lang)}
											<span class="lang-legend-item ds-caption">
												<span class="lang-dot" style="background: var(--tint-{l.tint})"></span>
												{l.lang}
											</span>
										{/each}
									</div>
								</div>
							{/if}
						</div>
					</RibbonCard>
				</div>
			{/each}
		</div>
	{/if}

	<CtaBlockRed>
		<p class="ds-body-sm cta-text">
			Ask the AI Assistant about your codebase &mdash; <a href="/chat">open chat &rarr;</a>
		</p>
	</CtaBlockRed>
</div>

<style>
	.toolbar {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		flex-wrap: wrap;
		padding: var(--space-lg);
		border-bottom: var(--border-hairline);
	}

	.spacer {
		flex: 1;
	}

	.filter-wrap {
		width: 260px;
		max-width: 100%;
	}

	.content {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
		padding: var(--space-lg);
	}

	.error-banner {
		border: var(--border-hairline);
		border-radius: var(--radius-md);
		background: var(--tint-salmon);
		color: var(--color-ink);
		padding: var(--space-sm) var(--space-md);
	}

	.retry-link {
		background: none;
		border: none;
		padding: 0;
		margin-left: var(--space-sm);
		color: var(--color-link);
		text-decoration: underline;
		cursor: pointer;
		font: inherit;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: var(--space-lg);
		align-items: start;
	}

	.skeleton-card {
		border: var(--border-hairline);
		border-radius: var(--radius-lg);
		background: var(--color-canvas);
		padding: var(--space-md) var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.empty-wrap {
		max-width: 640px;
	}

	.code-block {
		background: var(--color-page-backdrop);
		border: var(--border-hairline);
		border-radius: var(--radius-md);
		padding: var(--space-sm);
		overflow-x: auto;
	}

	.card {
		cursor: pointer;
		height: 100%;
	}

	.card:focus-visible {
		outline: 2px solid var(--color-link);
		outline-offset: 2px;
	}

	.card-body {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.card-head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.badges {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: var(--space-xxs);
	}

	.derived-tag {
		border: var(--border-hairline);
		border-radius: var(--radius-sm);
		background: var(--color-canvas);
		color: var(--color-ink-muted);
		padding: 2px var(--space-xs);
		white-space: nowrap;
	}

	.repo-chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	.repo-chip {
		background: var(--color-canvas);
		border: var(--border-hairline);
		border-radius: var(--radius-sm);
		padding: 2px var(--space-xs);
		cursor: pointer;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.repo-chip:hover {
		text-decoration: underline;
	}

	.counts {
		display: flex;
		gap: var(--space-lg);
	}

	.count-value {
		font-weight: 700;
	}

	.lang-bar-wrap {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.lang-bar {
		display: flex;
		height: 6px;
		border: var(--border-hairline);
		border-radius: var(--radius-full);
		overflow: hidden;
		background: var(--color-canvas);
	}

	.lang-seg {
		height: 100%;
	}

	.lang-legend {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-sm);
	}

	.lang-legend-item {
		display: inline-flex;
		align-items: center;
		gap: var(--space-xxs);
		color: var(--color-ink-muted);
	}

	.lang-dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border: var(--border-hairline);
	}

	.cta-text {
		margin: 0;
	}
</style>
