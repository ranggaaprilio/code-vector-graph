// API client — fetch wrappers, ported ~1:1 from the old js/api.js.
const BASE = '/api';

async function req<T = unknown>(path: string, opts: RequestInit = {}): Promise<T> {
	const res = await fetch(BASE + path, {
		headers: { 'Content-Type': 'application/json', ...opts.headers },
		...opts
	});
	if (!res.ok) {
		let detail = `${res.status} ${res.statusText}`;
		try {
			const j = await res.json();
			detail = j.detail || JSON.stringify(j);
		} catch {
			/* body wasn't JSON — keep the status line */
		}
		throw new Error(detail);
	}
	return res.json();
}

type QueryValue = string | number | boolean | null | undefined;

/** Build a query string from an object, skipping null / undefined / "" values. */
export function qs(obj: Record<string, QueryValue> = {}): string {
	const q = new URLSearchParams();
	for (const [k, v] of Object.entries(obj)) {
		if (v === null || v === undefined || v === '') continue;
		q.set(k, String(v));
	}
	const s = q.toString();
	return s ? `?${s}` : '';
}

const enc = encodeURIComponent;

/** Encode every segment of a slash-separated path but keep the slashes. */
function encPath(path: string): string {
	return String(path ?? '')
		.split('/')
		.map(enc)
		.join('/');
}

export type Scope = { app?: string; repo?: string };

/** Pick only the scope keys ({app, repo}) that carry a value. */
function scopeOf(scope: Scope = {}): Record<string, string> {
	const out: Record<string, string> = {};
	if (scope?.app) out.app = scope.app;
	if (scope?.repo) out.repo = scope.repo;
	return out;
}

// Health
export const getHealth = (deep = false) => req(`/health${qs({ deep: deep ? 'true' : null })}`);

// Applications
export const getApps = (refresh = false) =>
	req(`/apps${qs({ refresh: refresh ? 'true' : null })}`);
export const refreshApps = () => req('/apps/refresh', { method: 'POST' });
export const getApp = (name: string) => req(`/apps/${enc(name)}`);
export const getAppTree = (name: string, { repo, path }: { repo?: string; path?: string } = {}) =>
	req(`/apps/${enc(name)}/tree${qs({ repo, path })}`);
export const getAppFile = (name: string, repo: string, path: string) =>
	req(`/apps/${enc(name)}/files/${enc(repo)}/${encPath(path)}`);
export const getAppWiki = (name: string, params: Record<string, QueryValue> = {}) =>
	req(`/apps/${enc(name)}/wiki${qs(params)}`);
export const getAppWikiPage = (name: string, conceptId: string) =>
	req(`/apps/${enc(name)}/wiki/${enc(conceptId)}`);

// Qdrant
export const getCollections = () => req('/qdrant/collections');
export const getCollection = () => req('/qdrant/collection');
/** params may include: limit, offset, language, file_path, file_prefix, source, app, repo */
export const browsePoints = (params: Record<string, QueryValue> = {}) =>
	req(`/qdrant/points${qs(params)}`);
export const getPoint = (id: string) => req(`/qdrant/points/${enc(id)}`);

// Graph
export const getGraphStats = (scope: Scope = {}) => req(`/graph/stats${qs(scopeOf(scope))}`);
export const getNodes = (label: string, limit = 50, skip = 0, scope: Scope = {}) =>
	req(`/graph/nodes${qs({ label, limit, skip, ...scopeOf(scope) })}`);
export const getSubgraph = (nodeId: string, depth = 1, limit = 100) =>
	req(`/graph/subgraph${qs({ node_id: nodeId, depth, limit })}`);
export const runCypher = (cypher: string, params: Record<string, unknown> = {}, limit = 100) =>
	req('/graph/cypher', { method: 'POST', body: JSON.stringify({ cypher, params, limit }) });
/** Relationships whose both endpoints are among `ids` (max 200). */
export const getEdgesAmong = (ids: string[], limit = 500) =>
	req<{ edges: { id: string; from: string; to: string; type: string }[] }>('/graph/edges', {
		method: 'POST',
		body: JSON.stringify({ ids, limit })
	});

// Semantic search — body may include app, repo, include_wiki, source, top_k
export const searchCode = (body: Record<string, unknown>) =>
	req('/search', { method: 'POST', body: JSON.stringify(body) });

// Chat
export const getChatConfig = () => req('/chat/config');
export const chatSync = (body: Record<string, unknown>) =>
	req('/chat', { method: 'POST', body: JSON.stringify(body) });
