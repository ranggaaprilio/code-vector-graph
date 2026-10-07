// SSE chat client, ported ~1:1 from the old js/api.js. Uses fetch + a manual
// ReadableStream reader (not EventSource) because EventSource can't send a
// POST body.
const BASE = '/api';

type SseEvent = { event: string; data: string };

/**
 * Parse one SSE event block into {event, data}.
 * - comment lines (starting with ":") are ignored (sse-starlette pings)
 * - multiple "data:" lines are joined with "\n" per the SSE spec
 * - one optional leading space after the field colon is stripped
 */
function parseSseBlock(block: string): SseEvent | null {
	let event = 'message';
	const dataLines: string[] = [];
	for (const rawLine of block.split('\n')) {
		if (!rawLine || rawLine.startsWith(':')) continue;
		const colon = rawLine.indexOf(':');
		const field = colon === -1 ? rawLine : rawLine.slice(0, colon);
		let value = colon === -1 ? '' : rawLine.slice(colon + 1);
		if (value.startsWith(' ')) value = value.slice(1);
		if (field === 'event') event = value.trim() || 'message';
		else if (field === 'data') dataLines.push(value);
	}
	if (!dataLines.length) return null;
	return { event, data: dataLines.join('\n') };
}

export type ChatSource = Record<string, unknown>;

export type ChatStreamCallbacks = {
	onStatus?: (text: string) => void;
	onToken?: (text: string) => void;
	onSources?: (sources: ChatSource[]) => void;
	onDone?: (payload: unknown) => void;
	onError?: (text: string) => void;
};

/**
 * Stream chat over SSE. Returns an AbortController so the caller can stop it.
 * The backend (sse-starlette) separates lines with "\r\n"; normalised to "\n"
 * before splitting so blocks are detected regardless of the line ending used.
 */
export function chatStream(
	body: Record<string, unknown>,
	{ onStatus, onToken, onSources, onDone, onError }: ChatStreamCallbacks
): AbortController {
	const ctrl = new AbortController();

	const dispatch = (block: string) => {
		const evt = parseSseBlock(block);
		if (!evt) return;
		let parsed: Record<string, unknown>;
		try {
			parsed = JSON.parse(evt.data);
		} catch {
			return;
		}
		switch (evt.event) {
			case 'token':
				onToken?.((parsed.text as string) ?? '');
				break;
			case 'status':
				onStatus?.((parsed.text as string) ?? '');
				break;
			case 'sources':
				onSources?.((parsed.sources as ChatSource[]) ?? (parsed.data as ChatSource[]) ?? []);
				break;
			case 'done':
				onDone?.(parsed);
				break;
			case 'error':
				onError?.((parsed.text as string) ?? (parsed.detail as string) ?? 'Unknown error');
				break;
			default:
				break;
		}
	};

	const run = async () => {
		let res: Response;
		try {
			res = await fetch(`${BASE}/chat/stream`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
				signal: ctrl.signal
			});
		} catch (e) {
			if (!ctrl.signal.aborted) onError?.(String(e));
			return;
		}
		if (!res.ok) {
			let detail = `${res.status} ${res.statusText}`;
			try {
				const j = await res.json();
				detail = j.detail || detail;
			} catch {
				/* body wasn't JSON — keep the status line */
			}
			onError?.(detail);
			return;
		}
		if (!res.body) {
			onError?.('Response has no body');
			return;
		}

		const reader = res.body.getReader();
		const decoder = new TextDecoder();
		let buf = '';

		try {
			while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				buf += decoder.decode(value, { stream: true });
				buf = buf.replace(/\r\n?/g, '\n');

				let idx: number;
				while ((idx = buf.indexOf('\n\n')) !== -1) {
					const block = buf.slice(0, idx);
					buf = buf.slice(idx + 2);
					dispatch(block);
				}
			}
			// Flush any trailing block that was not terminated by a blank line.
			buf += decoder.decode();
			buf = buf.replace(/\r\n?/g, '\n');
			if (buf.trim()) dispatch(buf);
		} catch (e) {
			if (!ctrl.signal.aborted) onError?.(String(e));
		}
	};

	run();
	return ctrl;
}
