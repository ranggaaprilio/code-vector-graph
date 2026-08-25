// Shared formatting helpers — ported from the old vanilla-JS dashboard's
// js/lib/format.js. Router helpers (parseHash/buildHash) were dropped since
// SvelteKit's path-based routing replaces hash routing; everything else is
// close to a 1:1 port.
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import hljs from './highlight';

marked.use({ gfm: true, breaks: true });

/** Map an indexed `language` value (or wiki flag) to a highlight.js language id. */
export function hljsLang(language: unknown, isWiki = false): string {
	if (isWiki) return 'markdown';
	const l = String(language || '').toLowerCase();
	if (l === 'typescript' || l === 'tsx' || l === 'ts' || l === 'mts' || l === 'cts')
		return 'typescript';
	if (l === 'javascript' || l === 'jsx' || l === 'js' || l === 'mjs' || l === 'cjs')
		return 'javascript';
	if (hljs.getLanguage(l)) return l;
	return 'plaintext';
}

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

function stripTrailingSlashes(p: unknown): string {
	const s = String(p ?? '');
	return s.length > 1 ? s.replace(/\/+$/, '') : s;
}

export function basename(path: unknown): string {
	const s = stripTrailingSlashes(path);
	const i = s.lastIndexOf('/');
	return i === -1 ? s : s.slice(i + 1);
}

export function dirname(path: unknown): string {
	const s = stripTrailingSlashes(path);
	const i = s.lastIndexOf('/');
	if (i === -1) return '';
	if (i === 0) return '/';
	return s.slice(0, i);
}

export type Crumb = { name: string; path: string };

/** "a/b/c.js" -> [{name:"a",path:"a"},{name:"b",path:"a/b"},{name:"c.js",path:"a/b/c.js"}] */
export function breadcrumbs(path: unknown): Crumb[] {
	const s = String(path ?? '');
	const absolute = s.startsWith('/');
	const parts = s.split('/').filter(Boolean);
	const out: Crumb[] = [];
	let acc: string | null = absolute ? '' : null;
	for (const name of parts) {
		acc = acc === null ? name : `${acc}/${name}`;
		out.push({ name, path: acc });
	}
	return out;
}

/** Strip `root` (a directory prefix) from `filePath`; unchanged if it does not match. */
export function relToRoot(filePath: unknown, root: unknown): string {
	const fp = String(filePath ?? '');
	const r = stripTrailingSlashes(root ?? '');
	if (!r) return fp;
	if (fp === r) return '';
	const prefix = r.endsWith('/') ? r : `${r}/`;
	return fp.startsWith(prefix) ? fp.slice(prefix.length) : fp;
}

export type RepoRef = { name?: string | null; root?: string | null };

/**
 * Resolve the repo name a file belongs to.
 *   explicit  – a recorded `repo` payload value; wins when present.
 *   repos     – [{name, root}] candidates; the longest matching root prefix wins.
 */
export function repoOf(
	filePath: unknown,
	repos: RepoRef[] = [],
	explicit: string | null = null
): string | null {
	if (explicit) return explicit;
	const fp = String(filePath ?? '');
	if (!fp) return null;
	let best: string | null = null;
	let bestLen = -1;
	for (const r of repos || []) {
		const root = stripTrailingSlashes(r?.root ?? '');
		if (!root) continue;
		const matches = fp === root || fp.startsWith(root.endsWith('/') ? root : `${root}/`);
		if (matches && root.length > bestLen) {
			best = r.name ?? null;
			bestLen = root.length;
		}
	}
	return best;
}

/** True when a search result / point payload represents an OKF wiki page. */
export function isWiki(
	r: { source?: unknown; concept_id?: unknown } | null | undefined
): boolean {
	if (!r) return false;
	return r.source === 'wiki' || r.source === 'okf_wiki' || !!r.concept_id;
}

/** Sort an object's numeric values descending -> [[key, count], ...] limited to `n`. */
export function topEntries(
	obj: Record<string, number> | null | undefined,
	n?: number
): [string, number][] {
	const entries = Object.entries(obj || {}).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0));
	return typeof n === 'number' ? entries.slice(0, n) : entries;
}

/**
 * Normalise an application `languages` value into [[lang, count], ...] sorted
 * descending. Accepts `{ts: 12, js: 3}`, `["ts", "js"]` or `[{name, count}]`.
 */
export function langEntries(languages: unknown): [string, number][] {
	if (!languages) return [];
	if (Array.isArray(languages)) {
		const out: [string, number][] = [];
		for (const l of languages) {
			if (typeof l === 'string') out.push([l, 0]);
			else if (l && typeof l === 'object') {
				const obj = l as Record<string, unknown>;
				const name = obj.name ?? obj.language ?? obj.lang;
				if (name) {
					const count = Number(obj.count ?? obj.files ?? obj.chunks ?? 0) || 0;
					out.push([String(name), count]);
				}
			}
		}
		return out.sort((a, b) => b[1] - a[1]);
	}
	if (typeof languages === 'object') {
		return topEntries(languages as Record<string, number>).filter(
			([k, v]) => k && typeof v === 'number'
		);
	}
	return [];
}

// ---------------------------------------------------------------------------
// Scope helpers
// ---------------------------------------------------------------------------

/** "All applications" / "onebid · all repos" / "onebid · backend_nodejs_global_tnlm" */
export function scopeLabel(app: string, repo: string): string {
	if (!app) return 'All applications';
	return repo ? `${app} · ${repo}` : `${app} · all repos`;
}

export type AppInfo = { name?: string | null; repos?: RepoRef[] };

/** Locate a repo by name across all apps -> {app, repo} or null. */
export function findRepo(
	apps: AppInfo[],
	repoName: string
): { app: AppInfo; repo: RepoRef } | null {
	if (!repoName) return null;
	for (const a of apps || []) {
		for (const r of a?.repos || []) {
			if (r?.name === repoName) return { app: a, repo: r };
		}
	}
	return null;
}

export type ExplorerItem = {
	file_path?: string;
	repo?: string | null;
	rel_path?: string;
	app?: string;
};

export type ExplorerTarget = { app: string; repo: string; path: string };

/**
 * Resolve where a search hit / node / chat source lives in the file explorer.
 * Returns null when the repo cannot be determined.
 */
export function explorerTarget(
	apps: AppInfo[],
	item: ExplorerItem | null,
	preferredApp = ''
): ExplorerTarget | null {
	if (!item) return null;
	const allRepos = (apps || []).flatMap((a) => a?.repos || []);
	const repoName = repoOf(item.file_path, allRepos, item.repo || null);
	if (!repoName) return null;
	const hit = findRepo(apps, repoName);
	const appName = item.app || hit?.app?.name || preferredApp || '';
	if (!appName) return null;
	const root = hit?.repo?.root || '';
	const path = item.rel_path || relToRoot(item.file_path, root);
	return { app: appName, repo: repoName, path };
}

// ---------------------------------------------------------------------------
// Result formatting
// ---------------------------------------------------------------------------

export type LocatableResult = { file_path?: string; start_line?: number; end_line?: number };

/** Single implementation shared by vectors, chat and graph views. */
export function locationStr(result: LocatableResult | null | undefined): string {
	const { file_path, start_line, end_line } = result || {};
	if (!file_path) return 'unknown';
	const base = file_path.split('/').slice(-2).join('/');
	if (!start_line) return base;
	return end_line && end_line !== start_line ? `${base}:${start_line}-${end_line}` : `${base}:${start_line}`;
}

export function symbolStr(result: { function_name?: string; class_name?: string }): string {
	return result.function_name || result.class_name || '';
}

export function escapeHtml(str: unknown): string {
	return String(str)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// Markdown / syntax highlighting
// ---------------------------------------------------------------------------

/** Markdown -> sanitised HTML. */
export function renderMarkdown(md: string | null | undefined): string {
	if (!md) return '';
	return DOMPurify.sanitize(marked.parse(md, { async: false }));
}

/** Highlight every not-yet-highlighted <pre><code> under `rootEl`. */
export function highlightWithin(rootEl: ParentNode | null | undefined): void {
	if (!rootEl?.querySelectorAll) return;
	rootEl.querySelectorAll('pre code:not(.hljs)').forEach((el) => {
		hljs.highlightElement(el as HTMLElement);
	});
}

export async function copyToClipboard(text: string): Promise<boolean> {
	try {
		await navigator.clipboard.writeText(text);
		return true;
	} catch {
		return false;
	}
}
