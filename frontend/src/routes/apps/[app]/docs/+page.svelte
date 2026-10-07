<script lang="ts">
	import { tick } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import {
		getAppDocs,
		getAppDoc,
		saveAppDoc,
		regenerateAppDoc,
		generateAppDocs,
		reindexAppDoc,
		deleteAppDoc
	} from '$lib/api/client';
	import { ApiError } from '$lib/api/client';
	import { pollDocsJob, type DocsJob } from '$lib/api/jobs';
	import { renderMarkdown, renderMermaidWithin } from '$lib/utils/format';
	import { tintForLabel } from '$lib/utils/tints';
	import {
		RibbonCard,
		Button,
		TextInput,
		Select,
		Badge,
		Skeleton,
		EmptyState,
		Toast
	} from '$lib/components/ds';
	import MarkdownEditor from '$lib/components/editor/MarkdownEditor.svelte';
	import IndexingProgress from '$lib/components/jobs/IndexingProgress.svelte';
	import DocumentForm from './DocumentForm.svelte';

	type FeatureRow = {
		feature_id: string;
		slug?: string;
		title?: string;
		summary?: string;
		type?: 'Feature' | 'Document';
		kind?: string;
		category?: string;
		repo?: string;
		source?: string;
		stale?: boolean;
		member_count?: number;
		mention_count?: number;
		word_count?: number;
		tags?: string[];
		generated_at?: string;
		created_at?: string;
		edited_at?: string | null;
		needs_reembed?: boolean;
	};

	type FeaturePageDetail = {
		concept_id?: string;
		slug?: string;
		title?: string;
		summary?: string;
		overview?: string;
		content?: string;
		type?: 'Feature' | 'Document';
		kind?: string;
		category?: string;
		repo?: string;
		app?: string;
		source?: string;
		stale?: boolean;
		stale_since?: string | null;
		member_files?: string[];
		member_count?: number;
		word_count?: number;
		tags?: string[];
		generated_at?: string;
		created_at?: string;
		edited_at?: string | null;
		model?: string | null;
		language?: string;
		needs_reembed?: boolean;
		draft?: string | null;
	};

	type Member = {
		id?: string;
		label?: string;
		role?: string;
		name?: string;
		file_path?: string;
		start_line?: number;
	};

	type Mention = {
		id?: string;
		path?: string;
		rel_path?: string;
		repo?: string;
		token?: string;
	};

	type DocResponse = {
		page: FeaturePageDetail;
		members: Member[];
		mentions: Mention[];
		indexing_job: DocsJob | null;
		repo_root_accessible: boolean;
	};
	type ValidationIssue = { code: string; message: string; line?: number | null };
	type ValidationResult = { ok: boolean; errors: ValidationIssue[]; warnings: ValidationIssue[] };

	let { data }: {
		data: {
			appName: string;
			appDetail?: { repos?: { name: string }[] } | null;
			appError?: string | null;
		};
	} = $props();

	const LIMIT = 30;

	// ---- URL-derived filter/selection state ------------------------------
	const urlQ = $derived(page.url.searchParams.get('q') || '');
	const urlRepo = $derived(page.url.searchParams.get('repo') || '');
	const urlStale = $derived(page.url.searchParams.get('stale') || '');
	const urlSource = $derived(page.url.searchParams.get('source') || '');
	const urlOffset = $derived(Number(page.url.searchParams.get('offset') || 0) || 0);
	const urlType = $derived(page.url.searchParams.get('type') || '');
	const featureId = $derived(page.url.searchParams.get('feature') || '');
	const editMode = $derived(page.url.searchParams.get('edit') === '1');
	const creating = $derived(page.url.searchParams.get('new') === '1');

	const repoOptions = $derived(
		(data.appDetail?.repos || []).map((r) => r?.name).filter((n): n is string => !!n)
	);

	// ---- list state ---------------------------------------------------------
	let rows = $state<FeatureRow[]>([]);
	let total = $state(0);
	let listLoading = $state(false);
	let listError = $state<string | null>(null);
	let listSeq = 0;

	// ---- detail state ---------------------------------------------------------
	let detail = $state<DocResponse | null>(null);
	let detailLoading = $state(false);
	let detailError = $state<string | null>(null);
	let detailSeq = 0;

	// ---- edit state -------------------------------------------------------
	let editValue = $state('');
	let saving = $state(false);
	let saveIssues = $state<ValidationIssue[]>([]);

	// ---- regenerate state ---------------------------------------------------
	let draft = $state<{ body: string; grounding: string } | null>(null);
	let regenerating = $state(false);

	// ---- generate-docs job state --------------------------------------------
	let generateJob = $state<DocsJob | null>(null);
	let toastMessage = $state('');
	let generateJobAbort: AbortController | undefined;

	// ---- document/feature (re)index job state (create/edit/reindex) ---------
	let docJob = $state<DocsJob | null>(null);
	let docJobAbort: AbortController | undefined;
	let reindexing = $state(false);
	let confirmDelete = $state(false);
	let deleting = $state(false);

	// ---- search draft (decoupled from the URL for responsive typing) ----------
	let searchDraft = $state(page.url.searchParams.get('q') || '');
	let searchDebounceTimer: ReturnType<typeof setTimeout> | undefined;

	// ---- mermaid diagram rendering (```mermaid fences inside a page's content) ----
	let detailContentEl = $state<HTMLDivElement | undefined>(undefined);
	let draftPreviewEl = $state<HTMLDivElement | undefined>(undefined);

	async function loadList(
		appName: string,
		repo: string,
		q: string,
		stale: string,
		source: string,
		type: string,
		offset: number
	) {
		if (!appName) return;
		listLoading = true;
		listError = null;
		const seq = ++listSeq;
		try {
			const res = (await getAppDocs(appName, {
				repo: repo || undefined,
				q: q || undefined,
				stale: stale || undefined,
				source: source || undefined,
				type: type || 'all',
				kind: 'user-facing',
				limit: LIMIT,
				offset
			})) as { features?: FeatureRow[]; total?: number };
			if (seq !== listSeq) return;
			rows = res?.features || [];
			total = res?.total ?? rows.length;
		} catch (e) {
			if (seq !== listSeq) return;
			rows = [];
			total = 0;
			listError = String((e as Error)?.message || e);
		} finally {
			if (seq === listSeq) listLoading = false;
		}
	}

	async function loadDetail(appName: string, id: string) {
		docJobAbort?.abort();
		confirmDelete = false;
		if (!appName || !id) {
			detail = null;
			detailError = null;
			docJob = null;
			return;
		}
		detailLoading = true;
		detailError = null;
		draft = null;
		saveIssues = [];
		const seq = ++detailSeq;
		try {
			const res = (await getAppDoc(appName, id)) as DocResponse;
			if (seq !== detailSeq) return;
			detail = res;
			editValue = res?.page?.content || '';
			docJob = res.indexing_job;
			if (docJob && (docJob.status === 'queued' || docJob.status === 'running')) {
				watchDocJob(docJob.job_id);
			}
		} catch (e) {
			if (seq !== detailSeq) return;
			detail = null;
			detailError = String((e as Error)?.message || e);
		} finally {
			if (seq === detailSeq) detailLoading = false;
		}
	}

	$effect(() => {
		loadList(data.appName, urlRepo, urlQ, urlStale, urlSource, urlType, urlOffset);
	});

	$effect(() => {
		loadDetail(data.appName, featureId);
	});

	$effect(() => {
		searchDraft = urlQ;
	});

	// Render any ```mermaid fences to diagrams after Svelte patches each
	// prose container with new markdown — mirrors the highlightWithin() pattern
	// used for syntax highlighting elsewhere in the dashboard.
	$effect(() => {
		const content = detail?.page?.content;
		if (content && detailContentEl) {
			const el = detailContentEl;
			tick().then(() => renderMermaidWithin(el));
		}
	});

	$effect(() => {
		const body = draft?.body;
		if (body && draftPreviewEl) {
			const el = draftPreviewEl;
			tick().then(() => renderMermaidWithin(el));
		}
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

	function handleStaleChange(e: Event) {
		pushParams({ stale: (e.currentTarget as HTMLSelectElement).value, offset: 0 });
	}

	function handleSourceChange(e: Event) {
		pushParams({ source: (e.currentTarget as HTMLSelectElement).value, offset: 0 });
	}

	function handleRepoChange(e: Event) {
		pushParams({ repo: (e.currentTarget as HTMLSelectElement).value, offset: 0 });
	}

	function selectFeature(id: string) {
		pushParams({ feature: id, edit: null });
	}

	function clearSelection() {
		pushParams({ feature: null, edit: null });
	}

	function prevPage() {
		pushParams({ offset: Math.max(0, urlOffset - LIMIT) });
	}

	function nextPage() {
		pushParams({ offset: urlOffset + LIMIT });
	}

	function startEdit() {
		editValue = detail?.page?.content || '';
		saveIssues = [];
		pushParams({ edit: '1' });
	}

	function cancelEdit() {
		editValue = detail?.page?.content || '';
		saveIssues = [];
		pushParams({ edit: null });
	}

	function flashToast(msg: string, ms = 3000) {
		toastMessage = msg;
		setTimeout(() => {
			if (toastMessage === msg) toastMessage = '';
		}, ms);
	}

	async function saveEdit() {
		if (!detail?.page?.concept_id) return;
		saving = true;
		saveIssues = [];
		try {
			const res = (await saveAppDoc(data.appName, detail.page.concept_id, {
				markdown: editValue,
				category: detail.page.type === 'Document' ? detail.page.category : undefined,
				expected_edited_at: detail.page.edited_at ?? null
			})) as { page: FeaturePageDetail; validation: ValidationResult; reembedded: boolean; job_id?: string };
			detail = { ...detail, page: res.page };
			editValue = res.page.content || '';
			pushParams({ edit: null });
			if (res.job_id) {
				flashToast('Saved — indexing…', 2000);
				watchDocJob(res.job_id);
			} else {
				flashToast('Saved.', 2000);
			}
			loadList(data.appName, urlRepo, urlQ, urlStale, urlSource, urlType, urlOffset);
		} catch (e) {
			const detailValue = e instanceof ApiError ? e.detail : undefined;
			const validation =
				detailValue && typeof detailValue === 'object' && 'validation' in detailValue
					? (detailValue as { validation: ValidationResult }).validation
					: null;
			saveIssues = validation?.errors || [{ code: 'error', message: String((e as Error)?.message || e), line: null }];
		} finally {
			saving = false;
		}
	}

	async function doRegenerate() {
		if (!detail?.page?.concept_id) return;
		regenerating = true;
		try {
			const res = (await regenerateAppDoc(data.appName, detail.page.concept_id)) as {
				draft: string;
				grounding: string;
			};
			draft = { body: res.draft, grounding: res.grounding };
		} catch (e) {
			flashToast(String((e as Error)?.message || e));
		} finally {
			regenerating = false;
		}
	}

	function applyDraft() {
		if (!draft) return;
		editValue = draft.body;
		draft = null;
		if (!editMode) pushParams({ edit: '1' });
	}

	function discardDraft() {
		draft = null;
	}

	function watchGenerateJob(jobId: string) {
		generateJobAbort?.abort();
		generateJobAbort = new AbortController();
		pollDocsJob(data.appName, jobId, {
			signal: generateJobAbort.signal,
			onUpdate: (j) => (generateJob = j)
		})
			.then((job) => {
				generateJob = job;
				if (job.status === 'done') {
					const r = (job.result || {}) as Record<string, number>;
					flashToast(
						`Docs generated: ${r.generated ?? 0} new, ${r.cached ?? 0} cached, ` +
							`${r.kept_human ?? 0} kept, ${r.stale ?? 0} stale.`,
						5000
					);
				} else {
					flashToast(`Docs build failed: ${job.error || 'unknown error'}`, 5000);
				}
				loadList(data.appName, urlRepo, urlQ, urlStale, urlSource, urlType, urlOffset);
			})
			.catch(() => {});
	}

	async function startGenerate() {
		try {
			const res = (await generateAppDocs(data.appName, { repo: urlRepo || undefined })) as { job_id: string };
			generateJob = { job_id: res.job_id, status: 'queued', stages: ['generating', 'done'] } as DocsJob;
			watchGenerateJob(res.job_id);
		} catch (e) {
			const detailValue = e instanceof ApiError ? e.detail : undefined;
			const hint =
				detailValue && typeof detailValue === 'object' && 'hint' in detailValue
					? ` (${(detailValue as { hint: string }).hint})`
					: '';
			flashToast(String((e as Error)?.message || e) + hint, 6000);
		}
	}

	function watchDocJob(jobId: string) {
		docJobAbort?.abort();
		docJobAbort = new AbortController();
		pollDocsJob(data.appName, jobId, {
			signal: docJobAbort.signal,
			onUpdate: (j) => (docJob = j)
		})
			.then((job) => {
				docJob = job;
				loadList(data.appName, urlRepo, urlQ, urlStale, urlSource, urlType, urlOffset);
				if (job.status === 'done') loadDetail(data.appName, featureId);
			})
			.catch(() => {});
	}

	async function doReindex() {
		if (!detail?.page?.concept_id) return;
		reindexing = true;
		try {
			const res = (await reindexAppDoc(data.appName, detail.page.concept_id)) as { job_id: string };
			watchDocJob(res.job_id);
		} catch (e) {
			flashToast(String((e as Error)?.message || e));
		} finally {
			reindexing = false;
		}
	}

	function askDelete() {
		confirmDelete = true;
	}

	function cancelDeleteConfirm() {
		confirmDelete = false;
	}

	async function confirmDeleteDoc() {
		if (!detail?.page?.concept_id) return;
		deleting = true;
		try {
			await deleteAppDoc(data.appName, detail.page.concept_id);
			flashToast('Document deleted.', 3000);
			confirmDelete = false;
			clearSelection();
			loadList(data.appName, urlRepo, urlQ, urlStale, urlSource, urlType, urlOffset);
		} catch (e) {
			flashToast(String((e as Error)?.message || e));
		} finally {
			deleting = false;
		}
	}

	function startCreate() {
		pushParams({ new: '1', feature: null, edit: null });
	}

	function cancelCreate() {
		pushParams({ new: null });
	}

	function handleTypeChange(e: Event) {
		pushParams({ type: (e.currentTarget as HTMLSelectElement).value, offset: 0 });
	}

	function fileHref(path: string, repo?: string): string {
		const sp = new URLSearchParams();
		if (repo) sp.set('repo', repo);
		sp.set('path', path);
		return `/apps/${encodeURIComponent(data.appName)}/files?${sp.toString()}`;
	}

	// Abort any in-flight polling when the page is torn down.
	$effect(() => {
		return () => {
			generateJobAbort?.abort();
			docJobAbort?.abort();
		};
	});
</script>

<div class="docs-tab">
	<aside class="docs-sidebar">
		<div class="filters">
			<TextInput
				bind:value={searchDraft}
				oninput={handleSearchInput}
				placeholder="Search features…"
				aria-label="Search features"
			/>
			<Select value={urlStale} onchange={handleStaleChange} aria-label="Filter by staleness">
				<option value="">All</option>
				<option value="true">Stale only</option>
				<option value="false">Up to date</option>
			</Select>
			<Select value={urlSource} onchange={handleSourceChange} aria-label="Filter by source">
				<option value="">Any source</option>
				<option value="human">Edited</option>
				<option value="llm">AI-generated</option>
			</Select>
			{#if repoOptions.length}
				<Select value={urlRepo} onchange={handleRepoChange} aria-label="Filter by repository">
					<option value="">All repos</option>
					{#each repoOptions as r (r)}
						<option value={r}>{r}</option>
					{/each}
				</Select>
			{/if}
			<Select value={urlType} onchange={handleTypeChange} aria-label="Filter by page type">
				<option value="">All types</option>
				<option value="Feature">Features</option>
				<option value="Document">Documents</option>
			</Select>
			<Button variant="primary" onclick={startCreate}>New document</Button>
			<Button
				variant="secondary"
				loading={generateJob?.status === 'queued' || generateJob?.status === 'running'}
				onclick={startGenerate}
			>
				Generate docs
			</Button>
		</div>

		{#if generateJob && generateJob.status !== 'done'}
			<IndexingProgress job={generateJob} title="Generating docs" onDismiss={() => (generateJob = null)} />
		{/if}

		<div class="docs-list-scroll">
			{#if listLoading}
				<div class="list-skeleton">
					{#each Array(6) as _, i (i)}
						<Skeleton width="100%" height="48px" />
					{/each}
				</div>
			{:else if listError}
				<div class="list-message">
					<p class="ds-body-sm error-text">{listError}</p>
					<Button
						variant="secondary"
						onclick={() => loadList(data.appName, urlRepo, urlQ, urlStale, urlSource, urlType, urlOffset)}
					>
						Retry
					</Button>
				</div>
			{:else if !rows.length}
				<EmptyState title="No feature docs yet" tone="bare">
					<p class="ds-body-sm">
						Run <code>cvg-ingest --docs</code> or <code>cvg-docs-build</code>, or click
						"Generate docs" above.
					</p>
				</EmptyState>
			{:else}
				<ul class="docs-list">
					{#each rows as r (r.feature_id)}
						<li>
							<button
								type="button"
								class="docs-row"
								class:active={r.feature_id === featureId}
								onclick={() => selectFeature(r.feature_id)}
							>
								<div class="docs-row-top">
									<span class="ds-body-sm docs-title">{r.title}</span>
									<div class="docs-row-badges">
										{#if r.stale}<Badge label="Stale" />{/if}
										{#if r.type === 'Document'}
											<Badge label="Doc" kind="wiki" />
										{:else}
											<Badge label={r.source === 'human' ? 'Edited' : 'AI'} kind="wiki" />
										{/if}
									</div>
								</div>
								{#if r.summary}
									<p class="ds-caption docs-summary">{r.summary}</p>
								{/if}
								{#if r.repo && !urlRepo}
									<p class="ds-caption ds-mono docs-repo">{r.repo}</p>
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

	<div class="docs-detail">
		{#if creating}
			<DocumentForm
				appName={data.appName}
				repos={repoOptions}
				initialRepo={urlRepo}
				onCreated={(docId) => pushParams({ new: null, feature: docId })}
				onCancel={cancelCreate}
			/>
		{:else if !featureId}
			<div class="detail-placeholder ds-body-sm">&larr; Select a page from the list, or create a new document.</div>
		{:else}
			<Button variant="text-link" onclick={clearSelection}>&larr; All features</Button>

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
					<Button variant="secondary" onclick={() => loadDetail(data.appName, featureId)}>Retry</Button>
				</div>
			{:else if detail?.page}
				<RibbonCard title={detail.page.title} tint={tintForLabel(detail.page.type === 'Document' ? 'document' : (detail.page.kind || 'feature'))}>
					<div class="detail-meta">
						{#if detail.page.type === 'Document'}
							<Badge label="Document" />
							{#if detail.page.category}<Badge label={detail.page.category} />{/if}
						{:else if detail.page.kind}
							<Badge label={detail.page.kind} />
						{/if}
						<Badge label={detail.page.source === 'human' ? 'Edited' : 'AI-generated'} kind="wiki" />
						{#if detail.page.repo}
							<span class="ds-caption ds-mono">{detail.page.repo}</span>
						{:else if detail.page.type === 'Document'}
							<span class="ds-caption ds-mono">App-level</span>
						{/if}
						{#if detail.page.needs_reembed}<Badge label="Search index pending" />{/if}
					</div>

					{#if detail.page.type !== 'Document' && detail.page.stale}
						<div class="stale-banner">
							<p class="ds-body-sm">
								Code changed since this page was last {detail.page.source === 'human' ? 'edited' : 'generated'}.
							</p>
							<Button variant="secondary" loading={regenerating} onclick={doRegenerate}>
								Regenerate draft
							</Button>
						</div>
					{/if}

					{#if !editMode}
						<div class="detail-actions">
							<Button variant="secondary" onclick={startEdit}>Edit</Button>
							{#if detail.page.type === 'Document'}
								<Button variant="secondary" loading={reindexing} disabled={reindexing} onclick={doReindex}>
									Reindex
								</Button>
								{#if !confirmDelete}
									<Button variant="secondary" onclick={askDelete}>Delete</Button>
								{:else}
									<Button variant="secondary" onclick={cancelDeleteConfirm} disabled={deleting}>Cancel</Button>
									<Button variant="primary" loading={deleting} disabled={deleting} onclick={confirmDeleteDoc}>
										Confirm delete
									</Button>
								{/if}
							{:else if !detail.page.stale}
								<Button variant="secondary" loading={regenerating} disabled={regenerating} onclick={doRegenerate}>
									Regenerate draft
								</Button>
							{/if}
						</div>

						{#if docJob && docJob.status !== 'done'}
							<IndexingProgress job={docJob} onDismiss={() => (docJob = null)} />
						{/if}

						{#if detail.page.content}
							<div class="prose" bind:this={detailContentEl}>{@html renderMarkdown(detail.page.content)}</div>
						{:else if detail.page.summary}
							<p class="ds-body-sm detail-summary">{detail.page.summary}</p>
						{/if}

						{#if draft}
							<div class="draft-panel">
								<div class="draft-header">
									<p class="ds-h3">
										AI draft {draft.grounding === 'graph-only' ? '(graph-only — repo not readable here)' : ''}
									</p>
									<div class="draft-actions">
										<Button variant="secondary" onclick={discardDraft}>Discard</Button>
										<Button variant="primary" onclick={applyDraft}>Use this draft</Button>
									</div>
								</div>
								<div class="prose draft-prose" bind:this={draftPreviewEl}>{@html renderMarkdown(draft.body)}</div>
							</div>
						{/if}

						{#if detail.page.type === 'Document'}
							{#if detail.mentions?.length}
								<div class="chip-group">
									<p class="ds-caption chip-heading">Mentions</p>
									<div class="chips">
										{#each detail.mentions as m (m.id)}
											<a
												class="chip ds-caption"
												style="background: var(--tint-{tintForLabel('File')})"
												href={fileHref(m.rel_path || m.path || '', m.repo || detail.page.repo)}
												title={m.token}
											>
												{m.rel_path || m.path}
											</a>
										{/each}
									</div>
								</div>
							{/if}
						{:else if detail.members?.length}
							<div class="chip-group">
								<p class="ds-caption chip-heading">Implemented by</p>
								<div class="chips">
									{#each detail.members as m (m.id)}
										<a
											class="chip ds-caption"
											style="background: var(--tint-{tintForLabel(m.label || 'code')})"
											href={fileHref(m.file_path || '', detail.page.repo)}
										>
											{m.name}{m.role === 'entry_point' ? ' ⚡' : ''}
										</a>
									{/each}
								</div>
							</div>
						{/if}
					{:else}
						<div class="editor">
							{#if draft}
								<div class="draft-panel">
									<div class="draft-header">
										<p class="ds-h3">
											AI draft {draft.grounding === 'graph-only' ? '(graph-only)' : ''}
										</p>
										<div class="draft-actions">
											<Button variant="secondary" onclick={discardDraft}>Discard</Button>
											<Button variant="primary" onclick={applyDraft}>Use this draft</Button>
										</div>
									</div>
									<div class="prose draft-prose" bind:this={draftPreviewEl}>{@html renderMarkdown(draft.body)}</div>
								</div>
							{/if}

							{#if saveIssues.length}
								<div class="issues">
									{#each saveIssues as issue, i (i)}
										<p class="ds-body-sm issue">
											{#if issue.line}<span class="ds-mono">L{issue.line}</span>{/if}
											{issue.code}: {issue.message}
										</p>
									{/each}
								</div>
							{/if}

							{#if docJob && docJob.status !== 'done'}
								<IndexingProgress job={docJob} onDismiss={() => (docJob = null)} />
							{/if}

							<MarkdownEditor bind:value={editValue} minHeight="420px" />

							<div class="editor-actions">
								<Button variant="secondary" onclick={cancelEdit} disabled={saving}>Cancel</Button>
								{#if detail.page.type !== 'Document'}
									<Button variant="secondary" loading={regenerating} disabled={regenerating} onclick={doRegenerate}>
										Regenerate draft
									</Button>
								{/if}
								<Button variant="primary" loading={saving} disabled={saving} onclick={saveEdit}>Save</Button>
							</div>
						</div>
					{/if}
				</RibbonCard>
			{/if}
		{/if}
	</div>
</div>

<Toast message={toastMessage} onDismiss={() => (toastMessage = '')} />

<style>
	.docs-tab {
		display: flex;
		gap: var(--space-lg);
		padding: var(--space-lg);
		align-items: flex-start;
	}

	.docs-sidebar {
		width: 340px;
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

	.docs-list-scroll {
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

	.docs-list {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.docs-row {
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
	}

	.docs-row:hover {
		background: var(--color-row-hover);
	}

	.docs-row.active {
		background: var(--tint-sky);
	}

	.docs-row-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.docs-row-badges {
		display: flex;
		gap: var(--space-xxs);
		flex-shrink: 0;
	}

	.docs-title {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		flex: 1;
		min-width: 0;
	}

	.docs-summary {
		margin-top: var(--space-xxs);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.docs-repo {
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

	.docs-detail {
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
	}

	.stale-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm);
		background: var(--tint-peach);
		border-radius: var(--radius-md);
		padding: var(--space-sm) var(--space-md);
		margin-bottom: var(--space-md);
	}

	.detail-actions {
		display: flex;
		gap: var(--space-sm);
		margin-bottom: var(--space-md);
	}

	.draft-panel {
		margin-top: var(--space-md);
		border: var(--border-hairline);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		background: var(--tint-sky);
	}

	.draft-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm);
		margin-bottom: var(--space-sm);
	}

	.draft-actions {
		display: flex;
		gap: var(--space-xs);
	}

	.draft-prose {
		background: var(--color-canvas);
		border-radius: var(--radius-sm);
		padding: var(--space-sm);
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
		display: inline-block;
		border: var(--border-hairline);
		border-radius: var(--radius-sm);
		padding: 2px var(--space-xs);
		cursor: pointer;
		font: inherit;
		color: var(--color-ink);
		text-decoration: none;
	}

	.editor {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.issues {
		background: var(--tint-salmon);
		border-radius: var(--radius-md);
		padding: var(--space-sm) var(--space-md);
		display: flex;
		flex-direction: column;
		gap: var(--space-xxs);
	}

	.issue {
		color: var(--color-danger);
	}

	.editor-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-sm);
	}

	@media (max-width: 900px) {
		.docs-tab {
			flex-direction: column;
		}

		.docs-sidebar {
			width: 100%;
			position: static;
			max-height: none;
		}

		.docs-list-scroll {
			max-height: 360px;
		}
	}
</style>
