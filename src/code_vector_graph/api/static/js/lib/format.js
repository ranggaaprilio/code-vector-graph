// Shared formatting helpers, color palette, and utilities.
//
// This module must stay importable under plain Node (`node --test`): never touch
// `window`, `document`, `marked`, `DOMPurify` or `hljs` at import time — only
// check for those globals inside the functions that need them.

export const LABEL_COLORS = {
  File:         { bg: "bg-blue-600",    text: "text-blue-600",    cy: "#3b82f6" },
  Module:       { bg: "bg-blue-400",    text: "text-blue-400",    cy: "#60a5fa" },
  Class:        { bg: "bg-purple-600",  text: "text-purple-600",  cy: "#9333ea" },
  Interface:    { bg: "bg-purple-400",  text: "text-purple-400",  cy: "#c084fc" },
  TypeAlias:    { bg: "bg-pink-500",    text: "text-pink-500",    cy: "#ec4899" },
  Function:     { bg: "bg-green-600",   text: "text-green-600",   cy: "#16a34a" },
  Method:       { bg: "bg-green-400",   text: "text-green-400",   cy: "#4ade80" },
  Field:        { bg: "bg-yellow-500",  text: "text-yellow-500",  cy: "#eab308" },
  Variable:     { bg: "bg-orange-500",  text: "text-orange-500",  cy: "#f97316" },
  Import:       { bg: "bg-cyan-500",    text: "text-cyan-500",    cy: "#06b6d4" },
  Chunk:        { bg: "bg-gray-500",    text: "text-gray-500",    cy: "#6b7280" },
  GlossaryEntry:{ bg: "bg-rose-600",    text: "text-rose-600",    cy: "#e11d48" },
  WikiPage:     { bg: "bg-amber-500",   text: "text-amber-500",   cy: "#f59e0b" },
  Repository:   { bg: "bg-indigo-500",  text: "text-indigo-500",  cy: "#6366f1" },
  Application:  { bg: "bg-fuchsia-500", text: "text-fuchsia-500", cy: "#d946ef" },
};

export const NODE_LABELS = Object.keys(LABEL_COLORS);

export const LANG_COLORS = {
  typescript: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  javascript: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  tsx:        "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
};

/** Solid colours for language bars / dots (Tailwind classes above are for text badges). */
export const LANG_HEX = {
  typescript: "#3178c6",
  tsx:        "#5b9bd5",
  javascript: "#f1e05a",
  jsx:        "#f7df1e",
  python:     "#3572a5",
  markdown:   "#f59e0b",
  json:       "#a3a3a3",
  yaml:       "#cb171e",
  html:       "#e34c26",
  css:        "#563d7c",
  shell:      "#89e051",
  go:         "#00add8",
  rust:       "#dea584",
  java:       "#b07219",
};

export function langHex(lang) {
  return LANG_HEX[String(lang || "").toLowerCase()] || "#6b7280";
}

export function labelColor(label) {
  return LABEL_COLORS[label] || { bg: "bg-gray-400", text: "text-gray-400", cy: "#9ca3af" };
}

export function langBadge(lang) {
  return LANG_COLORS[lang] || "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200";
}

/** Map an indexed `language` value (or wiki flag) to a highlight.js language id. */
export function hljsLang(language, isWiki = false) {
  if (isWiki) return "markdown";
  const l = String(language || "").toLowerCase();
  if (l === "typescript" || l === "tsx" || l === "ts" || l === "mts" || l === "cts") return "typescript";
  if (l === "javascript" || l === "jsx" || l === "js" || l === "mjs" || l === "cjs") return "javascript";
  return "plaintext";
}

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

function stripTrailingSlashes(p) {
  const s = String(p ?? "");
  return s.length > 1 ? s.replace(/\/+$/, "") : s;
}

export function basename(path) {
  const s = stripTrailingSlashes(path);
  const i = s.lastIndexOf("/");
  return i === -1 ? s : s.slice(i + 1);
}

export function dirname(path) {
  const s = stripTrailingSlashes(path);
  const i = s.lastIndexOf("/");
  if (i === -1) return "";
  if (i === 0) return "/";
  return s.slice(0, i);
}

/** "a/b/c.js" -> [{name:"a",path:"a"},{name:"b",path:"a/b"},{name:"c.js",path:"a/b/c.js"}] */
export function breadcrumbs(path) {
  const s = String(path ?? "");
  const absolute = s.startsWith("/");
  const parts = s.split("/").filter(Boolean);
  const out = [];
  let acc = absolute ? "" : null;
  for (const name of parts) {
    acc = acc === null ? name : `${acc}/${name}`;
    out.push({ name, path: acc });
  }
  return out;
}

/** Strip `root` (a directory prefix) from `filePath`; unchanged if it does not match. */
export function relToRoot(filePath, root) {
  const fp = String(filePath ?? "");
  const r = stripTrailingSlashes(root ?? "");
  if (!r) return fp;
  if (fp === r) return "";
  const prefix = r.endsWith("/") ? r : `${r}/`;
  return fp.startsWith(prefix) ? fp.slice(prefix.length) : fp;
}

/**
 * Resolve the repo name a file belongs to.
 *   explicit  – a recorded `repo` payload value; wins when present.
 *   repos     – [{name, root}] candidates; the longest matching root prefix wins.
 * Returns the repo name or null.
 */
export function repoOf(filePath, repos = [], explicit = null) {
  if (explicit) return explicit;
  const fp = String(filePath ?? "");
  if (!fp) return null;
  let best = null;
  let bestLen = -1;
  for (const r of repos || []) {
    const root = stripTrailingSlashes(r?.root ?? "");
    if (!root) continue;
    const matches = fp === root || fp.startsWith(root.endsWith("/") ? root : `${root}/`);
    if (matches && root.length > bestLen) {
      best = r.name ?? null;
      bestLen = root.length;
    }
  }
  return best;
}

/** True when a search result / point payload represents an OKF wiki page. */
export function isWiki(r) {
  if (!r) return false;
  return r.source === "wiki" || r.source === "okf_wiki" || !!r.concept_id;
}

/** Sort an object's numeric values descending -> [[key, count], ...] limited to `n`. */
export function topEntries(obj, n) {
  const entries = Object.entries(obj || {}).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0));
  return typeof n === "number" ? entries.slice(0, n) : entries;
}

/**
 * Normalise an application `languages` value into [[lang, count], ...] sorted
 * descending. Accepts `{ts: 12, js: 3}`, `["ts", "js"]` or `[{name, count}]`.
 */
export function langEntries(languages) {
  if (!languages) return [];
  if (Array.isArray(languages)) {
    const out = [];
    for (const l of languages) {
      if (typeof l === "string") out.push([l, 0]);
      else if (l && typeof l === "object") {
        const name = l.name ?? l.language ?? l.lang;
        if (name) out.push([String(name), Number(l.count ?? l.files ?? l.chunks ?? 0) || 0]);
      }
    }
    return out.sort((a, b) => b[1] - a[1]);
  }
  if (typeof languages === "object") {
    return topEntries(languages).filter(([k, v]) => k && typeof v === "number");
  }
  return [];
}

// ---------------------------------------------------------------------------
// Router / scope helpers (pure; used by the Alpine store)
// ---------------------------------------------------------------------------

/** Default screen when the hash is empty. */
export const DEFAULT_VIEW = "apps";

/**
 * Parse a location hash into {view, segs, params}. The query string lives
 * *inside* the hash (changing `location.search` would reload the page):
 *   "#/apps/onebid/files?repo=x&path=src"
 *     -> {view:"apps", segs:["apps","onebid","files"], params:{repo:"x", path:"src"}}
 * Empty / "#" / "#/" -> {view:"apps", segs:["apps"], params:{}}.
 */
export function parseHash(hash) {
  let h = String(hash ?? "");
  if (h.startsWith("#")) h = h.slice(1);
  const qi = h.indexOf("?");
  const pathPart = qi === -1 ? h : h.slice(0, qi);
  const query = qi === -1 ? "" : h.slice(qi + 1);
  const segs = pathPart
    .split("/")
    .filter(Boolean)
    .map((seg) => {
      try { return decodeURIComponent(seg); } catch { return seg; }
    });
  if (!segs.length) segs.push(DEFAULT_VIEW);
  const params = {};
  for (const [k, v] of new URLSearchParams(query)) params[k] = v;
  return { view: segs[0], segs, params };
}

/**
 * Build a hash from a path and params, encoding each path segment and skipping
 * null / undefined / "" params:  buildHash("/apps/onebid/files", {repo:"x", path:""})
 *   -> "#/apps/onebid/files?repo=x"
 */
export function buildHash(path, params = {}) {
  const segs = String(path ?? "").split("/").filter(Boolean).map(encodeURIComponent);
  if (!segs.length) segs.push(DEFAULT_VIEW);
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v === null || v === undefined || v === "") continue;
    q.set(k, String(v));
  }
  const query = q.toString();
  return `#/${segs.join("/")}${query ? `?${query}` : ""}`;
}

/** "All applications" / "onebid · all repos" / "onebid · backend_nodejs_global_tnlm" */
export function scopeLabel(app, repo) {
  if (!app) return "All applications";
  return repo ? `${app} · ${repo}` : `${app} · all repos`;
}

/** Locate a repo by name across all apps -> {app, repo} or null. */
export function findRepo(apps, repoName) {
  if (!repoName) return null;
  for (const a of apps || []) {
    for (const r of a?.repos || []) {
      if (r?.name === repoName) return { app: a, repo: r };
    }
  }
  return null;
}

/**
 * Resolve where a search hit / node / chat source lives in the file explorer.
 *   item: {file_path, repo?, rel_path?, app?}
 * Returns {app, repo, path} or null when the repo cannot be determined.
 */
export function explorerTarget(apps, item, preferredApp = "") {
  if (!item) return null;
  const allRepos = (apps || []).flatMap((a) => a?.repos || []);
  const repoName = repoOf(item.file_path, allRepos, item.repo || null);
  if (!repoName) return null;
  const hit = findRepo(apps, repoName);
  const appName = item.app || hit?.app?.name || preferredApp || "";
  if (!appName) return null;
  const root = hit?.repo?.root || "";
  const path = item.rel_path || relToRoot(item.file_path, root);
  return { app: appName, repo: repoName, path };
}

// ---------------------------------------------------------------------------
// Result formatting
// ---------------------------------------------------------------------------

/** Single implementation shared by vectors, chat and graph views. */
export function locationStr(result) {
  const { file_path, start_line, end_line } = result || {};
  if (!file_path) return "unknown";
  const base = file_path.split("/").slice(-2).join("/");
  if (!start_line) return base;
  return end_line && end_line !== start_line ? `${base}:${start_line}-${end_line}` : `${base}:${start_line}`;
}

export function symbolStr(result) {
  return result.function_name || result.class_name || "";
}

export function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Markdown / syntax highlighting (browser-only globals checked at call time)
// ---------------------------------------------------------------------------

/** Markdown -> sanitised HTML. Falls back to escaped text when marked/DOMPurify are missing. */
export function renderMarkdown(md) {
  if (!md) return "";
  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") return escapeHtml(md);
  return DOMPurify.sanitize(marked.parse(md));
}

/** Highlight every not-yet-highlighted <pre><code> under `rootEl` (no-op without hljs). */
export function highlightWithin(rootEl) {
  if (typeof hljs === "undefined" || !rootEl?.querySelectorAll) return;
  rootEl.querySelectorAll("pre code:not(.hljs)").forEach((el) => hljs.highlightElement(el));
}

export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
