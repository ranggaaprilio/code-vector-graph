<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { appStore } from '$lib/stores/app.svelte';
	import { getAppWiki, getAppWikiPage } from '$lib/api/client';
	import { renderMarkdown } from '$lib/utils/format';
	import { tintForIndex, tintForLabel } from '$lib/utils/tints';
	import { RibbonCard, Button, TextInput, Select, Badge, Skeleton } from '$lib/components/ds';

	type WikiListItem = {
		concept_id: string;
		title: string;
		type?: string;
		summary?: string;
		repo?: string;
		path?: string;
		resource?: string;
	};

	type WikiDocument = { id?: string; label?: string; name?: string; file_path?: string } | null;

	type WikiRef = { concept_id: string; title: string; type?: string; summary?: string; repo?: string };

	type WikiPageDetail = {
		title?: string;
		summary?: string;
		overview?: string;
		how_it_works?: string;
		concept_id?: string;
		type?: string;
		repo?: string;
		resource?: string;
	};

	type WikiPageResponse = {
		page: WikiPageDetail;
		documents: WikiDocument;
		references: WikiRef[];
		referenced_by: WikiRef[];
	};

	let { data }: {
		data: {
			appName: string;
			appDetail?: { repos?: { name: string }[] } | null;
			appError?: string | null;
		};
	} = $props();

	const LIMIT = 30;

	// ---- URL-derived filter/selection state (source of truth for shareability) --
	const urlQ = $derived(page.url.searchParams.get('q') || '');
	const urlType = $derived(page.url.searchParams.get('type') || '');
	const urlRepo = $derived(page.url.searchParams.get('repo') || '');
	const urlOffset = $derived(Number(page.url.searchParams.get('offset') || 0) || 0);
	const conceptId = $derived(page.url.searchParams.get('concept') || '');

	const repoOptions = $derived(
		(data.appDetail?.repos || []).map((r) => r?.name).filter((n): n is string => !!n)
	);

	// ---- list state ---------------------------------------------------------
	let pages = $state<WikiListItem[]>([]);
	let total = $state(0);
	let listLoading = $state(false);
	let listError = $state<string | null>(null);
	let listSeq = 0;

	const sortedPages = $derived(
		[...pages].sort(
			(a, b) => (a.type || '').localeCompare(b.type || '') || (a.title || '').localeCompare(b.title || '')
		)
	);

	const wikiTypes = $derived.by(() => {
		const seen = new Set<string>();
		for (const p of pages) if (p.type) seen.add(p.type);
		if (urlType) seen.add(urlType);
		return [...seen].sort();
	});

	// ---- detail state ---------------------------------------------------------
	let detail = $state<WikiPageResponse | null>(null);
	let detailLoading = $state(false);
	let detailError = $state<string | null>(null);
	let detailSeq = 0;

	// ---- search draft (decoupled from the URL for responsive typing) ----------
	let searchDraft = $state(page.url.searchParams.get('q') || '');
	let searchDebounceTimer: ReturnType<typeof setTimeout> | undefined;

	async function loadList(appName: string, type: string, repo: string, q: string, offset: number) {
		if (!appName) return;
		listLoading = true;
		listError = null;
		const seq = ++listSeq;
		try {
			const res = (await getAppWiki(appName, {
				repo: repo || undefined,
				type: type || undefined,
				q: q || undefined,
				limit: LIMIT,
				offset
			})) as { pages?: WikiListItem[]; total?: number };
			if (seq !== listSeq) return;
			pages = res?.pages || [];
			total = res?.total ?? pages.length;
		} catch (e) {
			if (seq !== listSeq) return;
			pages = [];
			total = 0;
			listError = String((e as Error)?.message || e);
		} finally {
			if (seq === listSeq) listLoading = false;
		}
	}

	async function loadDetail(appName: string, id: string) {
		if (!appName || !id) {
			detail = null;
			detailError = null;
			return;
		}
		detailLoading = true;
		detailError = null;
		const seq = ++detailSeq;
		try {
			const res = (await getAppWikiPage(appName, id)) as WikiPageResponse;
			if (seq !== detailSeq) return;
			detail = res;
		} catch (e) {
			if (seq !== detailSeq) return;
			detail = null;
			detailError = String((e as Error)?.message || e);
		} finally {
			if (seq === detailSeq) detailLoading = false;
		}
	}

	// Reload the list whenever the app scope or any URL filter/page changes.
	$effect(() => {
		loadList(data.appName, urlType, urlRepo, urlQ, urlOffset);
	});

	// Reload the detail pane whenever the selected concept changes.
	$effect(() => {
		loadDetail(data.appName, conceptId);
	});

	// Keep the search box in sync when `q` changes from outside typing
	// (URL navigation, browser back/forward, app switch).
	$effect(() => {
		searchDraft = urlQ;
	});

	function pushParams(patch: Record<string, string | number | null>) {
		const sp = new URLSearchParams(page.url.searchParams);
		for (const [k, v] of Object.entries(patch)) {
			if (v === null || v === '' || v === 0) sp.delete(k);
			else sp.set(k, String(v));
		}
		const qs = sp.toString();
		goto(qs ? `?${qs}` : page.url.pathname, { replaceState: true, noScroll: true, keepFocus: true });
	}

	function handleSearchInput() {
		clearTimeout(searchDebounceTimer);
		const val = searchDraft;
		searchDebounceTimer = setTimeout(() => {
			if (val !== urlQ) pushParams({ q: val, offset: 0 });
		}, 300);
	}

	function handleTypeChange(e: Event) {
		const value = (e.currentTarget as HTMLSelectElement).value;
		pushParams({ type: value, offset: 0 });
	}

	function handleRepoChange(e: Event) {
		const value = (e.currentTarget as HTMLSelectElement).value;
		pushParams({ repo: value, offset: 0 });
	}

	function selectPage(id: string) {
		pushParams({ concept: id });
	}

	function clearSelection() {
		pushParams({ concept: null });
	}

	function prevPage() {
		pushParams({ offset: Math.max(0, urlOffset - LIMIT) });
	}

	function nextPage() {
		pushParams({ offset: urlOffset + LIMIT });
	}

	/** The page's `resource` ("src/a.ts#Symbol") mapped to a repo-relative path, when it isn't a URL. */
	function resourcePath(p?: WikiPageDetail | null): string {
		const res = p?.resource || '';
		if (!res || /^https?:\/\//i.test(res)) return '';
		return res.split('#')[0];
	}

	function fileHref(path: string, repo?: string): string {
		const sp = new URLSearchParams();
		if (repo) sp.set('repo', repo);
		sp.set('path', path);
		return `/apps/${encodeURIComponent(data.appName)}/files?${sp.toString()}`;
	}
</script>

<div class="wiki-tab">
	<aside class="wiki-sidebar">
		<div class="filters">
			<TextInput
				bind:value={searchDraft}
				oninput={handleSearchInput}
				placeholder="Search wiki pages…"
				aria-label="Search wiki pages"
			/>
			<Select value={urlType} onchange={handleTypeChange} aria-label="Filter by type">
				<option value="">All types</option>
				{#each wikiTypes as t (t)}
					<option value={t}>{t}</option>
				{/each}
			</Select>
			{#if repoOptions.length}
				<Select value={urlRepo} onchange={handleRepoChange} aria-label="Filter by repository">
					<option value="">All repos</option>
					{#each repoOptions as r (r)}
						<option value={r}>{r}</option>
					{/each}
				</Select>
			{/if}
		</div>

		<div class="wiki-list-scroll">
			{#if listLoading}
				<div class="list-skeleton">
					{#each Array(6) as _, i (i)}
						<Skeleton width="100%" height="40px" />
					{/each}
				</div>
			{:else if listError}
				<div class="list-message">
					<p class="ds-body-sm error-text">{listError}</p>
					<Button
						variant="secondary"
						onclick={() => loadList(data.appName, urlType, urlRepo, urlQ, urlOffset)}
					>
						Retry
					</Button>
				</div>
			{:else if !sortedPages.length}
				<p class="ds-body-sm empty-text">No wiki pages match these filters.</p>
			{:else}
				<ul class="wiki-list">
					{#each sortedPages as p (p.concept_id)}
						<li>
							<button
								type="button"
								class="wiki-row"
								class:active={p.concept_id === conceptId}
								onclick={() => selectPage(p.concept_id)}
							>
								<div class="wiki-row-top">
									<span class="ds-body-sm wiki-title">{p.title}</span>
									<Badge label={p.type || 'page'} />
								</div>
								{#if p.summary}
									<p class="ds-caption wiki-summary">{p.summary}</p>
								{/if}
								{#if p.repo && !urlRepo}
									<p class="ds-caption ds-mono wiki-repo">{p.repo}</p>
								{/if}
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		{#if total > LIMIT}
			<div class="pager">
				<Button variant="secondary" onclick={prevPage} disabled={urlOffset === 0}>&larr; Prev</Button>
				<span class="ds-caption pager-info">
					{urlOffset + 1}&ndash;{Math.min(urlOffset + LIMIT, total)} of {total}
				</span>
				<Button variant="secondary" onclick={nextPage} disabled={urlOffset + LIMIT >= total}>
					Next &rarr;
				</Button>
			</div>
		{/if}
	</aside>

	<div class="wiki-detail">
		{#if !conceptId}
			<div class="detail-placeholder ds-body-sm">&larr; Select a wiki page from the list.</div>
		{:else}
			<Button variant="text-link" onclick={clearSelection}>&larr; All pages</Button>

			{#if detailLoading}
				<div class="detail-skeleton">
					<Skeleton width="40%" height="20px" />
					<Skeleton width="100%" height="14px" />
					<Skeleton width="100%" height="14px" />
					<Skeleton width="80%" height="14px" />
				</div>
			{:else if detailError}
				<div class="list-message">
					<p class="ds-body-sm error-text">{detailError}</p>
					<Button variant="secondary" onclick={() => loadDetail(data.appName, conceptId)}>Retry</Button>
				</div>
			{:else if detail?.page}
				<RibbonCard title={detail.page.title} tint={tintForLabel(detail.page.type || 'page')}>
					<div class="detail-meta">
						{#if detail.page.type}<Badge label={detail.page.type} />{/if}
						{#if detail.page.repo}<span class="ds-caption ds-mono">{detail.page.repo}</span>{/if}
					</div>

					{#if detail.page.summary}
						<p class="ds-body-sm detail-summary">{detail.page.summary}</p>
					{/if}

					{#if detail.page.overview}
						<div class="prose">{@html renderMarkdown(detail.page.overview)}</div>
					{/if}

					{#if detail.page.how_it_works}
						<h3 class="ds-h3 how-it-works-heading">How it works</h3>
						<div class="prose">{@html renderMarkdown(detail.page.how_it_works)}</div>
					{/if}

					{#if detail.documents?.file_path}
						<Button
							variant="secondary"
							class="open-file-btn"
							href={fileHref(detail.documents.file_path, detail.page.repo)}
						>
							Open file
						</Button>
					{:else if resourcePath(detail.page)}
						<Button
							variant="secondary"
							class="open-file-btn"
							href={fileHref(resourcePath(detail.page), detail.page.repo)}
						>
							Open file
						</Button>
					{:else if detail.page.resource}
						<Button variant="secondary" class="open-file-btn" href={detail.page.resource} target="_blank" rel="noopener">
							Open source &#8599;
						</Button>
					{/if}

					{#if detail.references?.length}
						<div class="chip-group">
							<p class="ds-caption chip-heading">Related</p>
							<div class="chips">
								{#each detail.references as ref (ref.concept_id)}
									<button
										type="button"
										class="chip ds-caption"
										style="background: var(--tint-{tintForLabel(ref.type || 'concept')})"
										onclick={() => appStore.openWikiPage(ref.concept_id, { repo: ref.repo })}
									>
										{ref.title}
									</button>
								{/each}
							</div>
						</div>
					{/if}

					{#if detail.referenced_by?.length}
						<div class="chip-group">
							<p class="ds-caption chip-heading">Referenced by</p>
							<div class="chips">
								{#each detail.referenced_by as ref (ref.concept_id)}
									<button
										type="button"
										class="chip ds-caption"
										style="background: var(--tint-{tintForLabel(ref.type || 'concept')})"
										onclick={() => appStore.openWikiPage(ref.concept_id, { repo: ref.repo })}
									>
										{ref.title}
									</button>
								{/each}
							</div>
						</div>
					{/if}
				</RibbonCard>
			{/if}
		{/if}
	</div>
</div>

<style>
	.wiki-tab {
		display: flex;
		gap: var(--space-lg);
		padding: var(--space-lg);
		align-items: flex-start;
	}

	.wiki-sidebar {
		width: 320px;
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		position: sticky;
		top: var(--space-lg);
		max-height: calc(100vh - 160px);
	}

	.filters {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.wiki-list-scroll {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		border: var(--border-hairline);
		border-radius: var(--radius-lg);
		background: var(--color-canvas);
	}

	.list-skeleton {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		padding: var(--space-sm);
	}

	.list-message {
		padding: var(--space-md);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		align-items: flex-start;
	}

	.error-text {
		color: var(--color-danger);
	}

	.empty-text {
		padding: var(--space-md);
		color: var(--color-ink-muted);
	}

	.wiki-list {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.wiki-row {
		display: block;
		width: 100%;
		text-align: left;
		background: transparent;
		border: none;
		border-bottom: var(--border-hairline);
		padding: var(--space-sm) var(--space-md);
		cursor: pointer;
		font: inherit;
		color: inherit;
		transition: background-color var(--motion-fast) var(--ease-snap);
		content-visibility: auto;
		contain-intrinsic-size: auto 52px;
	}

	.wiki-row:hover {
		background: var(--color-row-hover);
	}

	.wiki-row.active {
		background: var(--tint-sky);
	}

	.wiki-row-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.wiki-title {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		flex: 1;
		min-width: 0;
	}

	.wiki-summary {
		margin-top: var(--space-xxs);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.wiki-repo {
		margin-top: var(--space-xxs);
	}

	.pager {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.pager-info {
		white-space: nowrap;
	}

	.wiki-detail {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.detail-placeholder {
		padding: var(--space-xxl);
		text-align: center;
		color: var(--color-ink-muted);
	}

	.detail-skeleton {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.detail-meta {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex-wrap: wrap;
		margin-bottom: var(--space-sm);
	}

	.detail-summary {
		color: var(--color-ink-muted);
		margin-bottom: var(--space-md);
	}

	.how-it-works-heading {
		margin-top: var(--space-md);
		margin-bottom: var(--space-xs);
	}

	:global(.open-file-btn) {
		margin-top: var(--space-md);
		align-self: flex-start;
	}

	.chip-group {
		margin-top: var(--space-lg);
	}

	.chip-heading {
		margin-bottom: var(--space-xs);
		text-transform: uppercase;
	}

	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	.chip {
		border: var(--border-hairline);
		border-radius: var(--radius-sm);
		padding: 2px var(--space-xs);
		cursor: pointer;
		font: inherit;
		color: var(--color-ink);
	}

	@media (max-width: 900px) {
		.wiki-tab {
			flex-direction: column;
		}

		.wiki-sidebar {
			width: 100%;
			position: static;
			max-height: none;
		}

		.wiki-list-scroll {
			max-height: 360px;
		}
	}
</style>
