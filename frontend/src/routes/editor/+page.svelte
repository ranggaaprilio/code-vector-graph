<script lang="ts">
	import { createAppDoc, ApiError } from '$lib/api/client';
	import { pollDocsJob, type DocsJob } from '$lib/api/jobs';
	import { RibbonCard, Button, Select, TextInput } from '$lib/components/ds';
	import MarkdownEditor from '$lib/components/editor/MarkdownEditor.svelte';
	import IndexingProgress from '$lib/components/jobs/IndexingProgress.svelte';
	import { extractTitle, wordCount } from '$lib/editor/stats';
	import { downloadMarkdown, suggestFilename } from '$lib/editor/files';
	import { clearDraft, loadDraft, saveDraft } from '$lib/editor/draft';
	import { appStore } from '$lib/stores/app.svelte';

	type ValidationIssue = { code: string; message: string; line?: number | null };

	const DRAFT_KEY = 'cvg.editor.draft';
	const MODE_KEY = 'cvg.editor.mode';
	const CATEGORIES = ['note', 'guide', 'adr', 'runbook', 'spec', 'other'];

	let value = $state('');
	let mode = $state<'split' | 'edit' | 'preview'>('split');
	let draftRestored = $state(false);
	let draftSaveTimer: ReturnType<typeof setTimeout> | undefined;

	let savePanelOpen = $state(false);
	let saveApp = $state('');
	let saveRepo = $state('');
	let saveCategory = $state('note');
	let saveTagsText = $state('');
	let saving = $state(false);
	let saveIssues = $state<ValidationIssue[]>([]);
	let saveJob = $state<DocsJob | null>(null);
	let savedDocId = $state<string | null>(null);
	let saveAbort: AbortController | undefined;

	const title = $derived(extractTitle(value));
	const saveRepos = $derived(appStore.apps.find((a) => a?.name === saveApp)?.repos || []);

	$effect(() => {
		const stored = loadDraft(DRAFT_KEY);
		if (stored) {
			value = stored;
			draftRestored = true;
		}
		const storedMode = loadDraft(MODE_KEY);
		if (storedMode === 'split' || storedMode === 'edit' || storedMode === 'preview') mode = storedMode;
		if (!saveApp) saveApp = appStore.app || '';
		if (!saveRepo) saveRepo = appStore.repo || '';
	});

	$effect(() => {
		saveDraft(MODE_KEY, mode);
	});

	$effect(() => {
		const val = value;
		clearTimeout(draftSaveTimer);
		draftSaveTimer = setTimeout(() => saveDraft(DRAFT_KEY, val), 800);
		return () => clearTimeout(draftSaveTimer);
	});

	$effect(() => {
		return () => saveAbort?.abort();
	});

	function onFileLoaded(name: string) {
		draftRestored = false;
	}

	function download() {
		downloadMarkdown(suggestFilename(title), value);
	}

	function clearAll() {
		value = '';
		clearDraft(DRAFT_KEY);
		draftRestored = false;
	}

	function toggleSavePanel() {
		savePanelOpen = !savePanelOpen;
		saveJob = null;
		savedDocId = null;
		saveIssues = [];
	}

	async function saveToDocs() {
		saving = true;
		saveIssues = [];
		try {
			const tags = saveTagsText
				.split(',')
				.map((t) => t.trim())
				.filter(Boolean);
			const res = (await createAppDoc(saveApp, {
				markdown: value,
				repo: saveRepo || null,
				tags,
				category: saveCategory
			})) as { job_id: string; doc_id: string };

			saveAbort?.abort();
			saveAbort = new AbortController();
			saveJob = {
				job_id: res.job_id,
				status: 'queued',
				stages: ['saving_graph', 'linking_mentions', 'embedding', 'upserting_vectors', 'writing_bundle', 'done']
			} as DocsJob;
			const finished = await pollDocsJob(saveApp, res.job_id, {
				signal: saveAbort.signal,
				onUpdate: (j) => (saveJob = j)
			});
			saveJob = finished;
			if (finished.status === 'done') savedDocId = res.doc_id;
		} catch (e) {
			const detailValue = e instanceof ApiError ? e.detail : undefined;
			const validation =
				detailValue && typeof detailValue === 'object' && 'validation' in detailValue
					? (detailValue as { validation: { errors: ValidationIssue[] } }).validation
					: null;
			saveIssues = validation?.errors || [{ code: 'error', message: String((e as Error)?.message || e), line: null }];
		} finally {
			saving = false;
		}
	}
</script>

<div class="editor-page">
	<div class="header">
		<div class="titleblock">
			<h1 class="ds-h1">{title || 'Untitled'}</h1>
			<p class="ds-caption">
				{wordCount(value)} words
				{#if draftRestored}&middot; draft restored from this browser{/if}
			</p>
		</div>
		<div class="header-actions">
			<Button variant="secondary" onclick={download}>Download .md</Button>
			<Button variant="secondary" onclick={clearAll}>Clear</Button>
			<Button variant="primary" onclick={toggleSavePanel}>Save to Docs&hellip;</Button>
		</div>
	</div>

	{#if savePanelOpen}
		<RibbonCard title="Save to Docs" tint="sky">
			{#if saveJob}
				<IndexingProgress job={saveJob} title="Indexing" onRetry={saveToDocs} onDismiss={() => (saveJob = null)} />
				{#if savedDocId}
					<Button variant="primary" href={`/apps/${encodeURIComponent(saveApp)}/docs?feature=${encodeURIComponent(savedDocId)}`}>
						Open in Docs
					</Button>
					<Button variant="text-link" onclick={clearAll}>Clear draft</Button>
				{/if}
			{:else}
				<div class="save-form">
					<Select bind:value={saveApp} aria-label="Application">
						<option value="">Select an application&hellip;</option>
						{#each appStore.apps as a (a.name)}
							<option value={a.name}>{a.name}</option>
						{/each}
					</Select>
					{#if saveRepos.length}
						<Select bind:value={saveRepo} aria-label="Repository">
							<option value="">App-level (no specific repo)</option>
							{#each saveRepos as r (r.name)}
								<option value={r.name}>{r.name}</option>
							{/each}
						</Select>
					{/if}
					<Select bind:value={saveCategory} aria-label="Category">
						{#each CATEGORIES as c (c)}
							<option value={c}>{c}</option>
						{/each}
					</Select>
					<TextInput bind:value={saveTagsText} placeholder="Tags, comma-separated" aria-label="Tags" />

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

					<div class="save-actions">
						<Button variant="secondary" onclick={toggleSavePanel} disabled={saving}>Cancel</Button>
						<Button variant="primary" loading={saving} disabled={saving || !saveApp} onclick={saveToDocs}>
							Create &amp; index
						</Button>
					</div>
				</div>
			{/if}
		</RibbonCard>
	{/if}

	<div class="editor-body">
		<MarkdownEditor bind:value bind:mode minHeight="calc(100vh - 260px)" {onFileLoaded} />
	</div>
</div>

<style>
	.editor-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
		padding: var(--space-lg);
	}

	.header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.header-actions {
		display: flex;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.save-form {
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

	.save-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-sm);
	}

	.editor-body {
		flex: 1;
		min-height: 0;
	}
</style>
