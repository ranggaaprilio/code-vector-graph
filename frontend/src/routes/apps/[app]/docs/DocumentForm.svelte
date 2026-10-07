<script lang="ts">
	import { createAppDoc, ApiError } from '$lib/api/client';
	import { pollDocsJob, type DocsJob } from '$lib/api/jobs';
	import { RibbonCard, Button, TextInput, Select } from '$lib/components/ds';
	import MarkdownEditor from '$lib/components/editor/MarkdownEditor.svelte';
	import IndexingProgress from '$lib/components/jobs/IndexingProgress.svelte';

	type ValidationIssue = { code: string; message: string; line?: number | null };

	let {
		appName,
		repos,
		initialRepo = '',
		onCreated,
		onCancel
	}: {
		appName: string;
		repos: string[];
		initialRepo?: string;
		onCreated: (docId: string) => void;
		onCancel: () => void;
	} = $props();

	const CATEGORIES = ['note', 'guide', 'adr', 'runbook', 'spec', 'other'];

	let title = $state('');
	let repo = $state(initialRepo);
	let category = $state('note');
	let tagsText = $state('');
	let markdown = $state('');
	let submitting = $state(false);
	let issues = $state<ValidationIssue[]>([]);
	let job = $state<DocsJob | null>(null);
	let abortController: AbortController | undefined;

	$effect(() => {
		return () => abortController?.abort();
	});

	async function submit() {
		submitting = true;
		issues = [];
		try {
			const tags = tagsText
				.split(',')
				.map((t) => t.trim())
				.filter(Boolean);
			const res = (await createAppDoc(appName, {
				title: title.trim() || undefined,
				markdown,
				repo: repo || null,
				tags,
				category
			})) as { job_id: string; doc_id: string };

			abortController?.abort();
			abortController = new AbortController();
			job = { job_id: res.job_id, status: 'queued', stages: ['saving_graph', 'linking_mentions', 'embedding', 'upserting_vectors', 'writing_bundle', 'done'] } as DocsJob;
			const finished = await pollDocsJob(appName, res.job_id, {
				signal: abortController.signal,
				onUpdate: (j) => (job = j)
			});
			job = finished;
			if (finished.status === 'done') {
				onCreated(res.doc_id);
			}
		} catch (e) {
			const detailValue = e instanceof ApiError ? e.detail : undefined;
			const validation =
				detailValue && typeof detailValue === 'object' && 'validation' in detailValue
					? (detailValue as { validation: { errors: ValidationIssue[] } }).validation
					: null;
			issues = validation?.errors || [{ code: 'error', message: String((e as Error)?.message || e), line: null }];
		} finally {
			submitting = false;
		}
	}
</script>

<RibbonCard title="New document" tint="sky">
	{#if job}
		<IndexingProgress job={job} title="Creating document" onRetry={submit} onDismiss={() => (job = null)} />
	{:else}
		<div class="form">
			<TextInput bind:value={title} placeholder="Title (or start the body with a # heading)" aria-label="Title" />
			{#if repos.length}
				<Select bind:value={repo} aria-label="Repository">
					<option value="">App-level (no specific repo)</option>
					{#each repos as r (r)}
						<option value={r}>{r}</option>
					{/each}
				</Select>
			{/if}
			<Select bind:value={category} aria-label="Category">
				{#each CATEGORIES as c (c)}
					<option value={c}>{c}</option>
				{/each}
			</Select>
			<TextInput bind:value={tagsText} placeholder="Tags, comma-separated" aria-label="Tags" />

			{#if issues.length}
				<div class="issues">
					{#each issues as issue, i (i)}
						<p class="ds-body-sm issue">
							{#if issue.line}<span class="ds-mono">L{issue.line}</span>{/if}
							{issue.code}: {issue.message}
						</p>
					{/each}
				</div>
			{/if}

			<MarkdownEditor bind:value={markdown} placeholder="# Title&#10;&#10;Write your document…" minHeight="360px" />

			<div class="actions">
				<Button variant="secondary" onclick={onCancel} disabled={submitting}>Cancel</Button>
				<Button variant="primary" loading={submitting} disabled={submitting} onclick={submit}>
					Create &amp; index
				</Button>
			</div>
		</div>
	{/if}
</RibbonCard>

<style>
	.form {
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

	.actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-sm);
	}
</style>
