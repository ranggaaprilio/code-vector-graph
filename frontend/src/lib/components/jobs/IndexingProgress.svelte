<script lang="ts">
	import { Button } from '$lib/components/ds';
	import { STAGE_LABELS, type DocsJob } from '$lib/api/jobs';

	let {
		job,
		title = 'Indexing',
		onRetry,
		onDismiss
	}: {
		job: DocsJob | null;
		title?: string;
		onRetry?: () => void;
		onDismiss?: () => void;
	} = $props();

	const stageLabel = (s: string) => STAGE_LABELS[s] ?? s;

	function stepState(stage: string): 'done' | 'active' | 'pending' {
		if (!job) return 'pending';
		const stages = job.stages;
		const idx = stages.indexOf(stage);
		const curIdx = job.stage ? stages.indexOf(job.stage) : -1;
		if (job.status === 'done') return 'done';
		if (idx < 0 || curIdx < 0) return 'pending';
		if (idx < curIdx) return 'done';
		if (idx === curIdx) return 'active';
		return 'pending';
	}

	const needsReembed = $derived(Boolean(job?.result?.needs_reembed));
</script>

{#if job}
	<div class="indexing-progress" aria-live="polite">
		<p class="ds-ui-label title">{title}</p>

		<ol class="steps">
			{#each job.stages.filter((s) => s !== 'done') as stage (stage)}
				<li class="step step-{stepState(stage)}">
					<span class="dot" aria-hidden="true"></span>
					<span class="ds-body-sm">{stageLabel(stage)}</span>
				</li>
			{/each}
		</ol>

		{#if job.message}
			<p class="ds-caption message">{job.message}</p>
		{/if}

		{#if job.progress && job.progress.total > 0}
			<div class="progress-row">
				<progress max={job.progress.total} value={job.progress.done}></progress>
				<span class="ds-caption">{job.progress.done} / {job.progress.total}</span>
			</div>
		{/if}

		{#if job.status === 'failed'}
			<div class="error-box">
				<p class="ds-body-sm error-text">{job.error || 'Something went wrong.'}</p>
				{#if onRetry}
					<Button variant="secondary" onclick={onRetry}>Retry</Button>
				{/if}
			</div>
		{:else if job.status === 'done'}
			<p class="ds-body-sm success-text">
				Done.
				{#if needsReembed}
					<span class="pending-note">Search index pending — no embedder is configured on this server.</span>
				{/if}
			</p>
		{/if}

		{#if onDismiss && (job.status === 'done' || job.status === 'failed')}
			<Button variant="text-link" onclick={onDismiss}>Dismiss</Button>
		{/if}
	</div>
{/if}

<style>
	.indexing-progress {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		border: var(--border-hairline);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		background: var(--color-canvas);
	}

	.title {
		text-transform: uppercase;
		color: var(--color-ink-muted);
	}

	.steps {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-xxs);
	}

	.step {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		border: 2px solid var(--color-hairline-strong);
		flex-shrink: 0;
	}

	.step-done .dot {
		background: var(--color-primary);
		border-color: var(--color-primary);
	}

	.step-active .dot {
		border-color: var(--color-primary);
		animation: pulse 1s ease-in-out infinite;
	}

	.step-pending span:last-child {
		color: var(--color-ink-muted);
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.35;
		}
	}

	.message {
		color: var(--color-ink-muted);
	}

	.progress-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.progress-row progress {
		flex: 1;
		accent-color: var(--color-primary);
	}

	.error-box {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		align-items: flex-start;
	}

	.error-text {
		color: var(--color-danger);
	}

	.success-text {
		color: var(--color-ink);
	}

	.pending-note {
		display: block;
		color: var(--color-warning, var(--color-ink-muted));
	}
</style>
