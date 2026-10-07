<script lang="ts">
	// Overview tab of the Application detail page. Renders ONLY the tab body —
	// the shared header, repo pills and tab strip live in the parent
	// +layout.svelte. Data comes from the layout's load() (GET /api/apps/{app}).
	import { RibbonCard, Badge, Skeleton } from '$lib/components/ds';
	import { tintForIndex } from '$lib/utils/tints';
	import { langEntries, renderMarkdown } from '$lib/utils/format';
	import { appStore } from '$lib/stores/app.svelte';

	// getApp() (see $lib/api/client.ts) returns `unknown` — there is no shared
	// response type yet, so the shape is declared locally from the FastAPI
	// handler (app_detail() in api/routers/apps.py).
	interface NodeCounts {
		functions?: number;
		methods?: number;
		classes?: number;
		interfaces?: number;
		type_aliases?: number;
		variables?: number;
		imports?: number;
		fields?: number;
		files?: number;
		chunks?: number;
		wiki_pages?: number;
		glossary?: number;
	}
	interface TopModule {
		path?: string;
		file_count?: number;
		chunk_count?: number;
	}
	interface RepoOverview {
		title?: string;
		summary?: string;
		overview?: string;
		how_it_works?: string;
		source?: 'wiki' | 'fallback';
		concept_id?: string;
		hint?: string;
	}
	interface RepoDetail {
		name: string;
		root?: string;
		file_count?: number;
		chunk_count?: number;
		counts?: NodeCounts;
		top_modules?: TopModule[];
		overview?: RepoOverview;
	}
	interface WikiTopItem {
		concept_id: string;
		title?: string;
		type?: string;
		summary?: string;
		repo?: string;
		path?: string;
		resource?: string;
	}
	interface AppDetail {
		counts?: NodeCounts;
		languages?: Record<string, number>;
		repos?: RepoDetail[];
		wiki_top?: WikiTopItem[];
	}

	let { data } = $props();
	const detail = $derived((data.appDetail ?? null) as AppDetail | null);

	// Node-type breakdown shown as horizontal bars in the Stats card. Files and
	// chunks get their own stat above the bars, so they're excluded here.
	const NODE_TYPE_LABELS: [keyof NodeCounts, string][] = [
		['functions', 'Functions'],
		['methods', 'Methods'],
		['classes', 'Classes'],
		['interfaces', 'Interfaces'],
		['type_aliases', 'Type aliases'],
		['variables', 'Variables'],
		['imports', 'Imports'],
		['fields', 'Fields']
	];

	function fmtNum(n: unknown): string {
		return Number(n || 0).toLocaleString();
	}

	const repos = $derived(detail?.repos ?? []);
	const wikiTop = $derived(detail?.wiki_top ?? []);
	const languages = $derived(langEntries(detail?.languages));

	const nodeTypeBars = $derived.by(() => {
		const counts = detail?.counts;
		if (!counts) return [];
		const rows = NODE_TYPE_LABELS.map(([key, label]) => ({
			key,
			label,
			value: Number(counts[key] || 0)
		})).filter((r) => r.value > 0);
		rows.sort((a, b) => b.value - a.value);
		const max = rows.length ? Math.max(1, rows[0].value) : 1;
		return rows.map((r, i) => ({
			...r,
			pct: Math.max(2, Math.round((r.value / max) * 100)),
			tint: tintForIndex(i)
		}));
	});

	function moduleLabel(m: TopModule): string {
		const path = m.path && m.path !== '.' ? m.path : '.';
		return `${path} (${fmtNum(m.file_count)})`;
	}

	function openWiki(item: WikiTopItem): void {
		appStore.openWikiPage(item.concept_id, { repo: item.repo });
	}
</script>

{#if data.appError}
	<p class="ds-body-sm error">{data.appError}</p>
{:else if !detail}
	<div class="loading">
		<Skeleton height="140px" />
		<Skeleton height="140px" />
	</div>
{:else}
	<div class="overview-grid">
		<div class="main-col">
			{#if repos.length}
				{#each repos as repo, i (repo.name)}
					<RibbonCard title={repo.name} tint={tintForIndex(i)}>
						{#if repo.root}
							<div class="repo-root ds-caption ds-mono">{repo.root}</div>
						{/if}

						{#if repo.overview?.source === 'fallback'}
							{#if repo.overview?.summary}
								<p class="ds-body-sm">{repo.overview.summary}</p>
							{/if}
							{#if repo.overview?.hint}
								<p class="ds-caption hint">
									No wiki overview yet for this repo. Generate one with:<br />
									<code class="ds-mono">{repo.overview.hint}</code>
								</p>
							{/if}
						{:else}
							<div class="prose">{@html renderMarkdown(repo.overview?.overview)}</div>
							{#if repo.overview?.how_it_works}
								<h3 class="ds-h3 subheading">How it fits together</h3>
								<div class="prose">{@html renderMarkdown(repo.overview.how_it_works)}</div>
							{/if}
						{/if}

						{#if repo.top_modules?.length}
							<div class="modules">
								<div class="ds-ui-label modules-label">Top modules</div>
								<div class="module-chips">
									{#each repo.top_modules as m (m.path)}
										<Badge label={moduleLabel(m)} kind="code" />
									{/each}
								</div>
							</div>
						{/if}
					</RibbonCard>
				{/each}
			{:else}
				<p class="ds-body-sm">No repositories indexed for this application.</p>
			{/if}
		</div>

		<aside class="side-col">
			<RibbonCard title="Stats" tint="steel">
				<div class="stat-row">
					<div class="stat">
						<div class="ds-caption">Files</div>
						<div class="ds-mono stat-value">{fmtNum(detail.counts?.files)}</div>
					</div>
					<div class="stat">
						<div class="ds-caption">Chunks</div>
						<div class="ds-mono stat-value">{fmtNum(detail.counts?.chunks)}</div>
					</div>
					<div class="stat">
						<div class="ds-caption">Wiki</div>
						<div class="ds-mono stat-value">{fmtNum(detail.counts?.wiki_pages)}</div>
					</div>
				</div>

				{#if nodeTypeBars.length}
					<div class="bars">
						{#each nodeTypeBars as bar (bar.key)}
							<div class="bar-row">
								<span class="ds-caption bar-label">{bar.label}</span>
								<div class="bar-track">
									<div
										class="bar-fill"
										style="width: {bar.pct}%; background: var(--tint-{bar.tint})"
									></div>
								</div>
								<span class="ds-caption ds-mono bar-value">{fmtNum(bar.value)}</span>
							</div>
						{/each}
					</div>
				{/if}
			</RibbonCard>

			{#if languages.length}
				<RibbonCard title="Languages" tint="sky">
					<div class="lang-chips">
						{#each languages as [lang, count] (lang)}
							<Badge label={count ? `${lang} (${fmtNum(count)})` : lang} />
						{/each}
					</div>
				</RibbonCard>
			{/if}

			{#if wikiTop.length}
				<RibbonCard title="Top wiki pages" tint="peach">
					<ul class="wiki-list">
						{#each wikiTop as item (item.concept_id)}
							<li>
								<button type="button" class="wiki-item" onclick={() => openWiki(item)}>
									<span class="ds-body-sm wiki-title">{item.title}</span>
									{#if item.summary}
										<span class="ds-caption wiki-summary">{item.summary}</span>
									{/if}
								</button>
							</li>
						{/each}
					</ul>
				</RibbonCard>
			{/if}
		</aside>
	</div>
{/if}

<style>
	.error {
		color: var(--color-danger);
		padding: var(--space-lg);
	}

	.loading {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
		padding: var(--space-lg);
	}

	.overview-grid {
		display: grid;
		grid-template-columns: 2fr 1fr;
		gap: var(--space-lg);
		padding: var(--space-lg);
		align-items: start;
	}

	@media (max-width: 900px) {
		.overview-grid {
			grid-template-columns: 1fr;
		}
	}

	.main-col,
	.side-col {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
		min-width: 0;
	}

	.repo-root {
		margin-bottom: var(--space-sm);
		word-break: break-all;
	}

	.subheading {
		margin-top: var(--space-md);
		margin-bottom: var(--space-xs);
	}

	.hint {
		margin-top: var(--space-sm);
	}

	.prose :global(p) {
		margin: 0 0 var(--space-sm) 0;
	}

	.prose :global(ul),
	.prose :global(ol) {
		margin: 0 0 var(--space-sm) var(--space-lg);
		padding: 0;
	}

	.prose :global(h1),
	.prose :global(h2),
	.prose :global(h3) {
		font-family: var(--font-heading);
		margin: var(--space-sm) 0 var(--space-xs);
	}

	.prose :global(code) {
		font-family: var(--font-mono);
		background: var(--color-row-zebra);
		border: var(--border-hairline);
		padding: 0 var(--space-xxs);
	}

	.prose :global(pre) {
		background: var(--color-page-backdrop);
		border: var(--border-hairline);
		padding: var(--space-sm);
		overflow-x: auto;
	}

	/* A <pre> already carries the slab chrome; don't double it on its <code>. */
	.prose :global(pre) > :global(code) {
		background: none;
		border: none;
		padding: 0;
	}

	.prose :global(a) {
		color: var(--color-link);
	}

	.modules {
		margin-top: var(--space-md);
	}

	.modules-label {
		margin-bottom: var(--space-xs);
	}

	.module-chips,
	.lang-chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	.stat-row {
		display: flex;
		gap: var(--space-lg);
		margin-bottom: var(--space-md);
	}

	.stat-value {
		font-size: var(--type-h2-size);
		font-weight: 700;
	}

	.bars {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.bar-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.bar-label {
		width: 90px;
		flex-shrink: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.bar-track {
		flex: 1;
		height: 6px;
		border: var(--border-hairline);
		border-radius: var(--radius-full);
		overflow: hidden;
		background: var(--color-canvas);
	}

	.bar-fill {
		height: 100%;
	}

	.bar-value {
		width: 40px;
		text-align: right;
		flex-shrink: 0;
	}

	.wiki-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.wiki-item {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 2px;
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		font: inherit;
		color: inherit;
	}

	.wiki-item:hover .wiki-title {
		text-decoration: underline;
	}

	.wiki-title {
		color: var(--color-link);
	}

	.wiki-summary {
		color: var(--color-ink-muted);
	}
</style>
