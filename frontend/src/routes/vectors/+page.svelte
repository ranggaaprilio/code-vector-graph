<script lang="ts">
	// Light syntax theme: a dark slab would be the only dark surface on the page.
	import 'highlight.js/styles/github.css';
	import { tick, onMount, untrack } from 'svelte';
	import { page as pageState } from '$app/state';
	import { SectionEyebrow, Button, TextInput, Select, Badge, Skeleton } from '$lib/components/ds';
	import { searchCode } from '$lib/api/client';
	import { appStore } from '$lib/stores/app.svelte';
	import {
		locationStr,
		symbolStr,
		isWiki,
		hljsLang,
		renderMarkdown,
		escapeHtml,
		copyToClipboard,
		highlightWithin
	} from '$lib/utils/format';

	// Shape returned by POST /search — see client.ts's SearchRequest/SearchResult contract.
	interface SearchResult {
		id: string;
		score: number;
		file_path: string;
		language: string;
		start_line?: number;
		end_line?: number;
		function_name?: string;
		class_name?: string;
		node_type?: string;
		text_content: string;
		imports: string[];
		exports: string[];
		symbols_defined: string[];
		call_sites: string[];
		token_count?: number;
		source: 'code' | 'wiki';
		summary?: string;
		term?: string;
		wiki_context?: Record<string, unknown>;
		app?: string;
		repo?: string;
		rel_path?: string;
		concept_id?: string;
	}

	const LANGUAGE_OPTIONS = ['', 'typescript', 'javascript', 'tsx'];
	const MODE_OPTIONS = ['hybrid', 'vector', 'graph'] as const;
	const TOP_K_OPTIONS = [10, 20, 50];
	const PAGE_SIZE = 10;

	let query = $state('');
	let language = $state('');
	let filePattern = $state('');
	let mode = $state<'hybrid' | 'vector' | 'graph'>('hybrid');
	let topK = $state(20);

	let results = $state<SearchResult[]>([]);
	let searching = $state(false);
	let hasSearched = $state(false);
	let error = $state<string | null>(null);
	let page = $state(0);

	let selected = $state<SearchResult | null>(null);
	/** Results belong to a scope the rail has since moved away from. */
	let staleScope = $state(false);
	let copied = $state(false);
	let detailEl: HTMLDivElement | undefined = $state();

	const totalPages = $derived(Math.max(1, Math.ceil(results.length / PAGE_SIZE)));
	const pageResults = $derived(results.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE));
	const canOpenInExplorer = $derived(selected ? !!appStore.explorerTarget(selected) : false);

	async function search() {
		if (!query.trim()) return;
		searching = true;
		error = null;
		try {
			const data = (await searchCode({
				query,
				mode,
				top_k: topK,
				language: language || undefined,
				file_pattern: filePattern || undefined,
				include_wiki: true,
				...appStore.scopeParams()
			})) as { results: SearchResult[]; query: string };
			results = data.results || [];
			hasSearched = true;
			staleScope = false;
			page = 0;
			selected = null;
		} catch (e) {
			error = String((e as Error)?.message || e);
		}
		searching = false;
	}

	function clearSearch() {
		query = '';
		results = [];
		hasSearched = false;
		staleScope = false;
		error = null;
		selected = null;
		page = 0;
	}

	function onQueryKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') search();
	}

	function selectResult(r: SearchResult) {
		selected = selected?.id === r.id ? null : r;
		copied = false;
	}

	// Highlight the code pane whenever a new (non-wiki) result is selected —
	// runs after Svelte has patched the DOM with the new text_content.
	$effect(() => {
		const current = selected;
		if (current && !isWiki(current) && detailEl) {
			tick().then(() => highlightWithin(detailEl));
		}
	});

	async function handleCopy() {
		if (!selected) return;
		const ok = await copyToClipboard(selected.text_content || '');
		copied = ok;
		if (ok) setTimeout(() => (copied = false), 2000);
	}

	function chipList(arr: string[] | undefined): string[] {
		return (arr || []).slice(0, 8);
	}

	/** App/repo chip shown next to a result when the scope is "All" or app-wide. */
	function repoLabel(r: SearchResult): string {
		const name = r.repo || '';
		return name && (!appStore.repo || appStore.repo !== name) ? name : '';
	}

	function wikiTitle(r: SearchResult): string {
		const wc = r.wiki_context as { title?: unknown } | undefined;
		return wc?.title ? String(wc.title) : '';
	}

	function wikiSummary(r: SearchResult): string {
		const wc = r.wiki_context as { summary?: unknown } | undefined;
		return wc?.summary ? String(wc.summary) : '';
	}

	// Hand-off from the file explorer arrives as ?q=&path= (see files/+page.svelte).
	// onMount rather than $effect: this must happen exactly once, and it must not
	// subscribe to the filter state it writes.
	onMount(() => {
		const q = pageState.url.searchParams.get('q') || '';
		const p = pageState.url.searchParams.get('path') || '';
		if (!q && !p) return;
		query = q;
		filePattern = p;
		if (q.trim()) search();
	});

	// The old dashboard refetched a view when the scope changed while it was
	// visible (js/lib/lazy.js). That was lost in the port, so results silently
	// belonged to the previous application. Re-run the query when there is one;
	// otherwise say the results are stale rather than quietly mutating them.
	let seenScope = appStore.scopeVersion;
	$effect(() => {
		const v = appStore.scopeVersion;
		if (v === seenScope) return;
		seenScope = v;
		untrack(() => {
			if (!hasSearched) return;
			if (query.trim()) search();
			else staleScope = true;
		});
	});
</script>

<SectionEyebrow title="Vector Search" tint="sky" />

<div class="vectors-page">
	<div class="filters">
		<div class="field query-field">
			<label class="ds-ui-label" for="vs-query">Query</label>
			<TextInput
				id="vs-query"
				placeholder="Semantic search…"
				bind:value={query}
				onkeydown={onQueryKeydown}
			/>
		</div>

		<div class="field">
			<label class="ds-ui-label" for="vs-language">Language</label>
			<Select
				id="vs-language"
				value={language}
				onchange={(e: Event) => (language = (e.target as HTMLSelectElement).value)}
			>
				{#each LANGUAGE_OPTIONS as l (l)}
					<option value={l}>{l || 'All languages'}</option>
				{/each}
			</Select>
		</div>

		<div class="field">
			<label class="ds-ui-label" for="vs-prefix">Path starts with</label>
			<TextInput
				id="vs-prefix"
				placeholder="src/…"
				bind:value={filePattern}
				onkeydown={onQueryKeydown}
			/>
		</div>

		<div class="field">
			<label class="ds-ui-label" for="vs-mode">Mode</label>
			<Select
				id="vs-mode"
				value={mode}
				onchange={(e: Event) =>
					(mode = (e.target as HTMLSelectElement).value as 'hybrid' | 'vector' | 'graph')}
			>
				{#each MODE_OPTIONS as m (m)}
					<option value={m}>{m}</option>
				{/each}
			</Select>
		</div>

		<div class="field">
			<label class="ds-ui-label" for="vs-topk">Top K</label>
			<Select
				id="vs-topk"
				value={String(topK)}
				onchange={(e: Event) => (topK = Number((e.target as HTMLSelectElement).value))}
			>
				{#each TOP_K_OPTIONS as k (k)}
					<option value={String(k)}>top {k}</option>
				{/each}
			</Select>
		</div>

		<div class="field actions">
			<Button variant="primary" onclick={search} disabled={searching || !query.trim()}>
				{searching ? '…' : 'Search'}
			</Button>
			{#if hasSearched}
				<Button variant="secondary" onclick={clearSearch}>Clear</Button>
			{/if}
		</div>
	</div>

	<div class="status-row ds-caption">
		<span>Scope: {appStore.scopeLabelText}</span>
		{#if hasSearched && !error}
			<span>· {results.length} found</span>
		{/if}
		{#if staleScope}
			<span class="stale">· scope changed — search again to refresh</span>
		{/if}
		{#if error}
			<span class="error">· {error}</span>
		{/if}
	</div>

	<div class="body">
		<div class="list-pane">
			{#if searching}
				<div class="skeleton-list">
					{#each Array(6) as _, i (i)}
						<div class="skeleton-row">
							<Skeleton width="40%" height="10px" />
							<Skeleton width="80%" height="12px" />
						</div>
					{/each}
				</div>
			{:else if !hasSearched}
				<div class="empty-state ds-body-sm muted">Enter a query above and press Search.</div>
			{:else if pageResults.length === 0}
				<div class="empty-state ds-body-sm muted">
					No results. Try a different search or filter.
				</div>
			{:else}
				{#each pageResults as r (r.id)}
					<button
						type="button"
						class="result-item"
						class:selected={selected?.id === r.id}
						onclick={() => selectResult(r)}
					>
						<div class="result-top">
							<Badge label={isWiki(r) ? 'wiki' : 'code'} />
							{#if repoLabel(r)}
								<span class="repo-chip ds-caption">{repoLabel(r)}</span>
							{/if}
							{#if r.score}
								<span class="score ds-caption">score {r.score.toFixed(3)}</span>
							{/if}
						</div>

						{#if isWiki(r)}
							<div class="result-title ds-body-sm">{r.term || 'Wiki page'}</div>
						{:else}
							<div class="result-location ds-mono ds-body-sm">{locationStr(r)}</div>
						{/if}

						<div class="result-meta">
							{#if !isWiki(r) && symbolStr(r)}
								<span class="ds-caption">{symbolStr(r)}</span>
							{/if}
							{#if !isWiki(r) && r.language}
								<Badge label={r.language} />
							{/if}
							{#if !isWiki(r) && r.node_type}
								<Badge label={r.node_type} />
							{/if}
						</div>

						{#if isWiki(r) && r.summary}
							<p class="result-summary ds-caption">{r.summary}</p>
						{/if}
						{#if !isWiki(r) && r.wiki_context}
							<div class="wiki-preview ds-caption">
								📖 {wikiTitle(r)}{wikiSummary(r) ? ` — ${wikiSummary(r)}` : ''}
							</div>
						{/if}
					</button>
				{/each}

				{#if results.length > PAGE_SIZE}
					<div class="pagination">
						<Button variant="secondary" disabled={page === 0} onclick={() => page--}
							>&larr; Prev</Button
						>
						<span class="ds-caption">Page {page + 1} of {totalPages}</span>
						<Button variant="secondary" disabled={page >= totalPages - 1} onclick={() => page++}
							>Next &rarr;</Button
						>
					</div>
				{/if}
			{/if}
		</div>

		<div class="detail-pane">
			{#if !selected}
				<div class="empty-state ds-body-sm muted">&larr; Select a result to view details</div>
			{:else}
				<div class="detail-header">
					<div class="detail-path-block">
						<div class="ds-mono ds-body-sm detail-path">{selected.file_path || selected.id}</div>
						{#if !isWiki(selected)}
							<div class="ds-caption muted">
								Lines {selected.start_line ?? '?'}–{selected.end_line ?? '?'} · {selected.token_count ??
									'?'} tokens
							</div>
						{/if}
					</div>
					{#if canOpenInExplorer}
						<Button variant="secondary" onclick={() => appStore.openInExplorer(selected)}
							>Open in Explorer</Button
						>
					{/if}
				</div>

				<div bind:this={detailEl}>
					{#if isWiki(selected)}
						<div class="wiki-body">
							{@html renderMarkdown(selected.summary || selected.text_content)}
						</div>
					{:else}
						<div class="code-block">
							<button type="button" class="copy-btn ds-caption" onclick={handleCopy}>
								{copied ? '✓ Copied' : 'Copy'}
							</button>
							<pre class="ds-mono ds-scroll-x"><code
									class={`hljs language-${hljsLang(selected.language)}`}
									>{escapeHtml(selected.text_content)}</code
								></pre>
						</div>
					{/if}
				</div>

				<div class="chips-grid">
					{#if chipList(selected.imports).length}
						<div class="chip-group">
							<div class="ds-ui-label muted">Imports</div>
							<div class="chip-row">
								{#each chipList(selected.imports) as imp (imp)}
									<Badge label={imp} />
								{/each}
							</div>
						</div>
					{/if}
					{#if chipList(selected.symbols_defined).length}
						<div class="chip-group">
							<div class="ds-ui-label muted">Symbols</div>
							<div class="chip-row">
								{#each chipList(selected.symbols_defined) as sym (sym)}
									<Badge label={sym} />
								{/each}
							</div>
						</div>
					{/if}
					{#if chipList(selected.call_sites).length}
						<div class="chip-group">
							<div class="ds-ui-label muted">Call Sites</div>
							<div class="chip-row">
								{#each chipList(selected.call_sites) as cs (cs)}
									<Badge label={cs} />
								{/each}
							</div>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>

<style>
	.vectors-page {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
	}

	.filters {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-md);
		padding: var(--space-lg);
		border-bottom: var(--border-hairline);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-xxs);
	}

	.query-field {
		flex: 1;
		min-width: 220px;
	}

	.actions {
		flex-direction: row;
		gap: var(--space-xs);
	}

	.status-row {
		display: flex;
		gap: var(--space-xs);
		padding: var(--space-xs) var(--space-lg);
		color: var(--color-ink-muted);
		border-bottom: var(--border-hairline);
	}

	.status-row .stale {
		font-weight: 700;
	}

	.status-row .error {
		color: var(--color-danger);
	}

	.body {
		display: flex;
		flex: 1;
		min-height: 0;
	}

	.list-pane {
		width: 50%;
		border-right: var(--border-hairline);
		overflow-y: auto;
		overscroll-behavior-y: contain;
	}

	.detail-pane {
		width: 50%;
		overflow-y: auto;
		overscroll-behavior-y: contain;
		padding: var(--space-lg);
	}

	.empty-state {
		padding: var(--space-xxl) var(--space-lg);
		text-align: center;
		color: var(--color-ink-muted);
	}

	.muted {
		color: var(--color-ink-muted);
	}

	.skeleton-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		padding: var(--space-md);
	}

	.skeleton-row {
		display: flex;
		flex-direction: column;
		gap: var(--space-xxs);
	}

	.result-item {
		display: block;
		width: 100%;
		text-align: left;
		background: var(--color-canvas);
		border: none;
		border-bottom: var(--border-hairline);
		padding: var(--space-sm) var(--space-md);
		cursor: pointer;
		font-family: inherit;
		color: inherit;
		transition: background-color var(--motion-fast) var(--ease-snap);
		/* Long result lists: let the browser skip rows that are scrolled away. */
		content-visibility: auto;
		contain-intrinsic-size: auto 64px;
	}

	.result-item:hover {
		background: var(--color-row-hover);
	}

	/* Selection reads as a rail, hover as a wash, so they never look the same. */
	.result-item.selected {
		background: var(--color-row-zebra);
		box-shadow: inset 3px 0 0 var(--color-link);
	}

	.result-top {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		flex-wrap: wrap;
	}

	.repo-chip {
		border: var(--border-hairline);
		border-radius: var(--radius-sm);
		padding: 2px var(--space-xs);
	}

	.score {
		margin-left: auto;
		color: var(--color-ink-muted);
		white-space: nowrap;
	}

	.result-location {
		margin-top: var(--space-xxs);
		word-break: break-all;
	}

	.result-title {
		margin-top: var(--space-xxs);
		font-weight: 700;
	}

	.result-meta {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		flex-wrap: wrap;
		margin-top: var(--space-xxs);
	}

	.result-summary {
		margin-top: var(--space-xxs);
		color: var(--color-ink-muted);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.wiki-preview {
		margin-top: var(--space-xxs);
		color: var(--color-ink-muted);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.pagination {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-md);
		padding: var(--space-md);
	}

	.detail-header {
		display: flex;
		align-items: flex-start;
		gap: var(--space-md);
		margin-bottom: var(--space-md);
	}

	.detail-path-block {
		flex: 1;
		min-width: 0;
	}

	.detail-path {
		word-break: break-all;
	}

	.wiki-body {
		border: var(--border-hairline);
		border-radius: var(--radius-lg);
		background: var(--color-page-backdrop);
		padding: var(--space-md);
		margin-bottom: var(--space-lg);
	}

	.wiki-body :global(h1),
	.wiki-body :global(h2),
	.wiki-body :global(h3) {
		font-family: var(--font-heading);
		text-transform: uppercase;
		margin: var(--space-md) 0 var(--space-xs);
	}

	.wiki-body :global(p) {
		margin: var(--space-xs) 0;
	}

	.wiki-body :global(code) {
		font-family: var(--font-mono);
		background: var(--color-canvas);
		padding: 0 2px;
	}

	.wiki-body :global(pre) {
		overflow-x: auto;
	}

	.code-block {
		position: relative;
		margin-bottom: var(--space-lg);
	}

	.code-block pre {
		margin: 0;
		padding: var(--space-md);
	}

	.copy-btn {
		position: absolute;
		top: var(--space-xs);
		right: var(--space-xs);
		z-index: 1;
		background: var(--color-canvas);
		border: var(--border-hairline);
		border-radius: var(--radius-sm);
		padding: 2px var(--space-xs);
		cursor: pointer;
		color: var(--color-ink);
	}

	.chips-grid {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.chip-group .ds-ui-label {
		margin-bottom: var(--space-xxs);
	}

	.chip-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	@media (max-width: 768px) {
		.body {
			flex-direction: column;
		}

		.list-pane,
		.detail-pane {
			width: 100%;
			max-height: none;
		}

		.list-pane {
			border-right: none;
			border-bottom: var(--border-hairline);
		}
	}
</style>
