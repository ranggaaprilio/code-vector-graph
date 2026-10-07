// Polling helper + shared types for background doc-indexing jobs
// (DocsJobManager on the server — api/services/docs_jobs.py). Two kinds
// share this shape: "generate" (a full Feature-doc build) and
// "index_document" (create/update/reindex one manually-authored Document).
import { getDocsJob } from './client';

export type DocsJobStatus = 'queued' | 'running' | 'done' | 'failed';
export type DocsJobKind = 'generate' | 'index_document';

export type DocsJobTarget = { doc_id: string; slug: string; title: string };

export type DocsJob = {
	job_id: string;
	app: string;
	repo: string | null;
	kind: DocsJobKind;
	status: DocsJobStatus;
	stage: string | null;
	stages: string[];
	message: string | null;
	progress: { done: number; total: number } | null;
	target: DocsJobTarget | null;
	started_at: number | null;
	finished_at: number | null;
	result?: Record<string, unknown> | null;
	error?: string | null;
};

export const STAGE_LABELS: Record<string, string> = {
	saving_graph: 'Saving to knowledge graph',
	linking_mentions: 'Linking mentioned files',
	embedding: 'Embedding',
	upserting_vectors: 'Writing vectors',
	writing_bundle: 'Mirroring to bundle',
	generating: 'Generating feature docs',
	done: 'Done'
};

export class DocsJobPollAborted extends Error {}

/** Poll `GET /apps/{app}/docs/jobs/{jobId}` until it reaches a terminal
 * status, calling `onUpdate` after every fetch. Uses a non-overlapping
 * `setTimeout` loop (not `setInterval`) so a slow request never piles up
 * concurrent polls; pass an `AbortSignal` (aborted on component teardown)
 * to stop early — this is what the previous `setInterval`-based polling on
 * the Docs page leaked on unmount. */
export function pollDocsJob(
	app: string,
	jobId: string,
	opts: { intervalMs?: number; signal?: AbortSignal; onUpdate?: (job: DocsJob) => void } = {}
): Promise<DocsJob> {
	const { intervalMs = 2000, signal, onUpdate } = opts;

	return new Promise((resolve, reject) => {
		let timer: ReturnType<typeof setTimeout> | undefined;

		const onAbort = () => {
			clearTimeout(timer);
			reject(new DocsJobPollAborted('Polling aborted'));
		};
		signal?.addEventListener('abort', onAbort, { once: true });

		const tick = async () => {
			if (signal?.aborted) return;
			try {
				const job = (await getDocsJob(app, jobId)) as DocsJob;
				if (signal?.aborted) return;
				onUpdate?.(job);
				if (job.status === 'done' || job.status === 'failed') {
					signal?.removeEventListener('abort', onAbort);
					resolve(job);
					return;
				}
				timer = setTimeout(tick, intervalMs);
			} catch (e) {
				if (signal?.aborted) return;
				signal?.removeEventListener('abort', onAbort);
				reject(e);
			}
		};

		tick();
	});
}
