<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { Button, Badge, RibbonCard, Skeleton } from '$lib/components/ds';
	import { tintForIndex, nodeStyle, nodeShape } from '$lib/utils/tints';
	import {
		breadcrumbs,
		hljsLang,
		escapeHtml,
		renderMarkdown,
		copyToClipboard,
		highlightWithin
	} from '$lib/utils/format';
	import { getAppTree, getAppFile } from '$lib/api/client';
	import { appStore } from '$lib/stores/app.svelte';
	// Light syntax theme: a dark slab would be the only dark surface in an
	// otherwise all-light catalog page.
	import 'highlight.js/styles/github.css';

	let { data } = $props();

	// ---------------------------------------------------------------------
	// URL-derived navigation state: ?repo=&path=&file=
	//   repo  – selected repository name ('' -> show the repo picker)
	//   path  – directory currently listed within the repo
	//   file  – repo-relative path of the selected file (shown in the code pane)
	// ---------------------------------------------------------------------
	let repo = $derived(page.url.searchParams.get('repo') || '');
	let dirPath = $derived(page.url.searchParams.get('path') || '');
	let filePath = $derived(page.url.searchParams.get('file') || '');

	function updateUrl(next: Record<string, string | null>): void {
		const q = new URLSearchParams(page.url.searchParams);
		for (const [k, v] of Object.entries(next)) {
			if (v) q.set(k, v);
			else q.delete(k);
		}
		const s = q.toString();
		goto(s ? `?${s}` : '', { replaceState: true, noScroll: true, keepFocus: true });
	}

	function selectRepo(name: string): void {
		updateUrl({ repo: name, path: null, file: null });
	}

	function backToRepos(): void {
		updateUrl({ repo: null, path: null, file: null });
	}

	function openDir(path: string): void {
		updateUrl({ path: path || null, file: null });
	}

	function openFile(path: string): void {
		updateUrl({ file: path });
	}

	// ---------------------------------------------------------------------
	// Directory tree
	// ---------------------------------------------------------------------
	type TreeRepo = { name: string; root: string; file_count: number; source?: string };
	type TreeDir = { name: string; path: string; file_count: number };
	type TreeFile = {
		name: string;
		path: string;
		abs_path?: string;
		language?: string;
		file_id?: string;
		line_count?: number;
		chunk_count?: number;
	};
	type TreeResponse =
		| { kind: 'repos'; repos: TreeRepo[] }
		| { kind: 'dir'; path: string; dirs: TreeDir[]; files: TreeFile[] };

	let tree = $state<TreeResponse | null>(null);
	let treeLoading = $state(false);
	let treeError = $state<string | null>(null);

	$effect(() => {
		const appName = data.appName;
		const r = repo;
		const p = dirPath;
		let cancelled = false;
		treeLoading = true;
		treeError = null;
		getAppTree(appName, { repo: r || undefined, path: p || undefined })
			.then((res) => {
				if (cancelled) return;
				tree = res as TreeResponse;
			})
			.catch((e) => {
				if (cancelled) return;
				tree = null;
				treeError = String((e as Error)?.message || e);
			})
			.finally(() => {
				if (!cancelled) treeLoading = false;
			});
		return () => {
			cancelled = true;
		};
	});

	const crumbs = $derived(breadcrumbs(dirPath));
	const treeRepos = $derived(tree?.kind === 'repos' ? tree.repos : []);
	const treeDirs = $derived(tree?.kind === 'dir' ? tree.dirs : []);
	const treeFiles = $derived(tree?.kind === 'dir' ? tree.files : []);

	// ---------------------------------------------------------------------
	// Selected file detail
	// ---------------------------------------------------------------------
	type Symbol = {
		id: string;
		label: string;
		name: string;
		start_line: number;
		end_line: number;
		is_exported?: boolean;
		wiki?: { concept_id?: string; title?: string; summary?: string; type?: string } | null;
	};
	type Chunk = {
		id: string;
		chunk_index: number;
		start_line: number;
		end_line: number;
		function_name?: string;
		class_name?: string;
		node_type?: string;
		text_content: string;
		language?: string;
		token_count?: number;
		symbols_defined?: string[];
		source?: string;
	};
	type WikiPage = {
		id?: string;
		concept_id?: string;
		type?: string;
		title?: string;
		summary?: string;
		overview?: string;
		how_it_works?: string;
		resource?: string;
	};
	type FileDetail = {
		file: {
			id: string;
			path: string;
			rel_path: string;
			repo: string;
			app: string;
			language?: string;
			line_count?: number;
			exports?: unknown[];
			imports?: unknown[];
		};
		symbols: Symbol[];
		chunks: Chunk[];
		wiki: WikiPage[];
		glossary?: unknown[];
	};

	let fileDetail = $state<FileDetail | null>(null);
	let fileLoading = $state(false);
	let fileError = $state<string | null>(null);
	let activeSymbolId = $state<string | null>(null);
	let activeChunkId = $state<string | null>(null);
	let copiedChunkId = $state<string | null>(null);
	let chunksEl = $state<HTMLElement | null>(null);

	$effect(() => {
		const appName = data.appName;
		const r = repo;
		const f = filePath;
		if (!r || !f) {
			fileDetail = null;
			fileError = null;
			return;
		}
		let cancelled = false;
		fileLoading = true;
		fileError = null;
		activeSymbolId = null;
		activeChunkId = null;
		getAppFile(appName, r, f)
			.then((res) => {
				if (cancelled) return;
				fileDetail = res as FileDetail;
			})
			.catch((e) => {
				if (cancelled) return;
				fileDetail = null;
				fileError = String((e as Error)?.message || e);
			})
			.finally(() => {
				if (!cancelled) fileLoading = false;
			});
		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		// Re-run whenever the chunk list changes and the pane is mounted.
		if (fileDetail && chunksEl) {
			highlightWithin(chunksEl);
		}
	});

	function chunkLabel(c: Chunk): string {
		return `L${c.start_line ?? '?'}–${c.end_line ?? '?'}`;
	}

	function chunkTitle(c: Chunk): string {
		return c.function_name || c.class_name || c.node_type || '';
	}

	async function copyChunk(c: Chunk): Promise<void> {
		const ok = await copyToClipboard(c.text_content || '');
		if (!ok) return;
		copiedChunkId = c.id;
		setTimeout(() => {
			if (copiedChunkId === c.id) copiedChunkId = null;
		}, 2000);
	}

	function focusSymbol(sym: Symbol): void {
		activeSymbolId = sym.id;
		const start = Number(sym.start_line || 0);
		const end = Number(sym.end_line || start);
		const hit = (fileDetail?.chunks || []).find(
			(c) => Number(c.end_line ?? 0) >= start && Number(c.start_line ?? 0) <= end
		);
		activeChunkId = hit?.id || null;
		if (!hit) return;
		requestAnimationFrame(() => {
			document
				.getElementById(`chunk-${hit.id}`)
				?.scrollIntoView({ behavior: 'smooth', block: 'start' });
		});
	}

	// Cross-view hand-offs. The old Alpine app stashed a `prefill` bag on its
	// global store; the context now travels in the URL instead, so a hand-off
	// survives a hard refresh and can be shared as a link — which the in-memory
	// bag never could.
	function handOff(path: string, params: Record<string, string>): void {
		const f = fileDetail?.file;
		if (!f) return;
		appStore.setScope(f.app || data.appName, f.repo || repo);
		const q = new URLSearchParams(params);
		if (f.app) q.set('app', f.app);
		if (f.repo) q.set('repo', f.repo);
		goto(`${path}?${q}`);
	}

	function showInVectors(): void {
		const f = fileDetail?.file;
		if (!f) return;
		// Search the file's own name, narrowed to the file itself, so the results
		// are that file's chunks rather than a repo-wide match.
		const name = f.rel_path.split('/').pop() || f.rel_path;
		handOff('/vectors', { q: name, path: f.rel_path });
	}

	function openInGraph(): void {
		const f = fileDetail?.file;
		if (!f?.id) return;
		handOff('/graph', { node: f.id });
	}

	function askInChat(): void {
		const f = fileDetail?.file;
		if (!f) return;
		handOff('/chat', { file: f.rel_path });
	}
</script>

<div class="files-tab">
	<div class="tree-pane">
		<div class="crumbs ds-body-sm">
			{#if repo}
				<Button variant="text-link" onclick={backToRepos}>&larr; All repos</Button>
				<span class="sep">/</span>
				<Button variant="text-link" onclick={() => openDir('')}>{repo}</Button>
				{#each crumbs as c (c.path)}
					<span class="sep">/</span>
					<Button variant="text-link" onclick={() => openDir(c.path)}>{c.name}</Button>
				{/each}
			{:else}
				<span class="ds-ui-label">Repositories</span>
			{/if}
		</div>

		<div class="tree-list">
			{#if treeLoading}
				<div class="tree-loading">
					{#each Array(6) as _, i (i)}
						<Skeleton height="18px" />
					{/each}
				</div>
			{:else if treeError}
				<p class="ds-body-sm error">{treeError}</p>
			{:else}
				{#each treeRepos as r (r.name)}
					<button class="tree-row ds-body-sm" onclick={() => selectRepo(r.name)}>
						<span class="ds-mono truncate">{r.name}</span>
						<span class="row-meta ds-caption">{r.file_count}</span>
					</button>
				{/each}

				{#each treeDirs as d (d.path)}
					<button class="tree-row ds-body-sm" onclick={() => openDir(d.path)}>
						<span class="icon">&#128193;</span>
						<span class="truncate">{d.name}</span>
						<span class="row-meta ds-caption">{d.file_count}</span>
					</button>
				{/each}

				{#each treeFiles as f (f.path)}
					<button
						class="tree-row ds-body-sm"
						class:active={filePath === f.path}
						onclick={() => openFile(f.path)}
					>
						<span class="icon">&#128196;</span>
						<span class="truncate">{f.name}</span>
						{#if f.language}
							<span class="row-badge"><Badge label={f.language} /></span>
						{/if}
					</button>
				{/each}

				{#if !treeRepos.length && !treeDirs.length && !treeFiles.length}
					<p class="ds-body-sm empty">Empty.</p>
				{/if}
			{/if}
		</div>
	</div>

	<div class="code-pane">
		{#if fileLoading}
			<div class="pane-center ds-body-sm">Loading&hellip;</div>
		{:else if fileError}
			<p class="ds-body-sm error pane-pad">{fileError}</p>
		{:else if !fileDetail}
			<div class="pane-center ds-body-sm empty">Select a file</div>
		{:else}
			<header class="code-header">
				<span class="ds-mono file-path truncate">{fileDetail.file.rel_path}</span>
				<div class="actions">
					<Button variant="secondary" onclick={showInVectors}>Chunks in Vectors</Button>
					<Button variant="secondary" onclick={openInGraph}>Open in Graph</Button>
					<Button variant="secondary" onclick={askInChat}>Ask in Chat</Button>
				</div>
			</header>

			<div class="code-body">
				<div class="symbols-pane">
					{#if !fileDetail.symbols.length}
						<p class="ds-body-sm empty pane-pad">No symbols.</p>
					{:else}
						{#each fileDetail.symbols as s (s.id)}
							<button
								class="symbol-row ds-body-sm"
								class:active={activeSymbolId === s.id}
								onclick={() => focusSymbol(s)}
							>
								<span
									class="ds-swatch"
									data-shape={nodeShape(s.label)}
									style="background: var(--tint-{nodeStyle(s.label).tint})"
								></span>
								<span class="ds-mono truncate">{s.name}</span>
								<span class="row-meta ds-caption">{s.start_line}</span>
							</button>
						{/each}
					{/if}
				</div>

				<div class="chunks-pane" bind:this={chunksEl}>
					{#if !fileDetail.chunks.length}
						<p class="ds-body-sm empty">No chunks indexed for this file.</p>
					{:else}
						{#each fileDetail.chunks as c (c.id)}
							<div class="chunk" id={`chunk-${c.id}`} class:chunk-active={activeChunkId === c.id}>
								<div class="chunk-header ds-caption">
									<span>{chunkLabel(c)}</span>
									{#if chunkTitle(c)}
										<span class="chunk-title ds-mono">{chunkTitle(c)}</span>
									{/if}
									<Button
										variant="text-link"
										class="chunk-copy"
										onclick={() => copyChunk(c)}
									>
										{copiedChunkId === c.id ? '✓ Copied' : 'Copy'}
									</Button>
								</div>
								<pre><code class="language-{hljsLang(c.language || fileDetail.file.language)}">{escapeHtml(c.text_content)}</code></pre>
							</div>
						{/each}
					{/if}
				</div>
			</div>
		{/if}
	</div>

	<div class="wiki-pane">
		{#if fileDetail}
			{#if !fileDetail.wiki.length}
				<p class="ds-body-sm empty pane-pad">
					No wiki page documents this file. Run <span class="ds-mono">cvg-okf-build</span> +
					<span class="ds-mono">cvg-okf-sync</span>.
				</p>
			{:else}
				{#each fileDetail.wiki as w, i (w.id || w.concept_id || i)}
					<div class="wiki-card">
						<RibbonCard title={w.title} tint={tintForIndex(i)}>
							{#if w.type}
								<div class="ds-caption wiki-type">{w.type}</div>
							{/if}
							{#if w.summary}
								<p class="ds-body-sm">{w.summary}</p>
							{/if}
							{#if w.overview}
								<div class="ds-body-sm wiki-md">{@html renderMarkdown(w.overview)}</div>
							{/if}
						</RibbonCard>
					</div>
				{/each}
			{/if}
		{/if}
	</div>
</div>

<style>
	.files-tab {
		display: flex;
		height: 100%;
		min-height: 60vh;
	}

	.tree-pane {
		width: 260px;
		flex-shrink: 0;
		border-right: var(--border-hairline);
		display: flex;
		flex-direction: column;
		min-height: 0;
	}

	.crumbs {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-xxs);
		padding: var(--space-sm);
		border-bottom: var(--border-hairline);
	}

	.sep {
		color: var(--color-ink-muted);
	}

	.tree-list {
		flex: 1;
		overflow-y: auto;
	}

	.tree-loading {
		padding: var(--space-sm);
		display: flex;
		flex-direction: column;
		gap: var(--space-s);
	}

	.tree-row {
		width: 100%;
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		padding: var(--space-xs) var(--space-sm);
		background: transparent;
		border: none;
		border-bottom: 1px solid transparent;
		text-align: left;
		cursor: pointer;
		color: var(--color-ink);
		transition: background-color var(--motion-fast) var(--ease-snap);
		content-visibility: auto;
		contain-intrinsic-size: auto 28px;
	}

	.tree-row:hover {
		background: var(--color-row-hover);
	}

	/* Inset rail rather than a real border: a 2px border would shift the row. */
	.tree-row.active {
		background: var(--color-row-zebra);
		box-shadow: inset 2px 0 0 var(--color-link);
	}

	.truncate {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}

	.row-meta {
		margin-left: auto;
		flex-shrink: 0;
	}

	.row-badge {
		margin-left: auto;
		flex-shrink: 0;
	}

	.icon {
		flex-shrink: 0;
	}

	.empty {
		color: var(--color-ink-muted);
		padding: var(--space-sm);
	}

	.error {
		color: var(--color-danger);
		padding: var(--space-sm);
	}

	.pane-pad {
		padding: var(--space-md);
	}

	.code-pane {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}

	.pane-center {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--color-ink-muted);
	}

	.code-header {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		flex-wrap: wrap;
		padding: var(--space-sm) var(--space-md);
		border-bottom: var(--border-hairline);
	}

	.file-path {
		color: var(--color-link);
		min-width: 0;
	}

	.actions {
		display: flex;
		gap: var(--space-xs);
		margin-left: auto;
		flex-wrap: wrap;
	}

	.code-body {
		flex: 1;
		display: flex;
		min-height: 0;
		overflow: hidden;
	}

	.symbols-pane {
		width: 220px;
		flex-shrink: 0;
		border-right: var(--border-hairline);
		overflow-y: auto;
	}

	.symbol-row {
		width: 100%;
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		padding: var(--space-xs) var(--space-sm);
		background: transparent;
		border: none;
		text-align: left;
		cursor: pointer;
		color: var(--color-ink);
		transition: background-color var(--motion-fast) var(--ease-snap);
	}

	.symbol-row:hover {
		background: var(--color-row-hover);
	}

	.symbol-row.active {
		background: var(--color-row-zebra);
		box-shadow: inset 2px 0 0 var(--color-link);
	}

	.chunks-pane {
		flex: 1;
		overflow-y: auto;
		padding: var(--space-md);
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.chunk {
		border: var(--border-hairline);
		border-radius: var(--radius-md);
	}

	.chunk-active {
		outline: 2px solid var(--color-link);
		outline-offset: -2px;
	}

	.chunk-header {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xxs) var(--space-sm);
		background: var(--color-page-backdrop);
		border-bottom: var(--border-hairline);
	}

	.chunk-title {
		color: var(--color-ink-muted);
	}

	.chunk-header :global(.chunk-copy) {
		margin-left: auto;
	}

	/* The syntax pane keeps highlight.js's own theme (github light) — mapping
	   source tokens onto 8 catalog tints would cost readability. Everything
	   around the pane still comes from the token system. */
	.chunk pre {
		margin: 0;
		overflow-x: auto;
		padding: var(--space-sm);
	}

	.chunk code {
		font-family: var(--font-mono);
		font-size: var(--type-body-sm-size);
	}

	.wiki-pane {
		width: 300px;
		flex-shrink: 0;
		border-left: var(--border-hairline);
		overflow-y: auto;
		padding: var(--space-md);
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.wiki-card {
		flex-shrink: 0;
	}

	.wiki-type {
		text-transform: uppercase;
		margin-bottom: var(--space-xs);
	}

	.wiki-md {
		margin-top: var(--space-xs);
	}

	.wiki-md :global(p) {
		margin: 0 0 var(--space-xs) 0;
	}
</style>
