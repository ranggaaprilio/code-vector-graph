// API client — all fetch wrappers and SSE helper
const BASE = "/api";

async function req(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const j = await res.json(); detail = j.detail || JSON.stringify(j); } catch {}
    throw new Error(detail);
  }
  return res.json();
}

/**
 * Build a query string from an object, skipping null / undefined / "" values.
 * Returns "" when nothing survives, otherwise "?a=1&b=2".
 */
export function qs(obj = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(obj)) {
    if (v === null || v === undefined || v === "") continue;
    q.set(k, v);
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

// Health
export const getHealth = (deep = false) => req(`/health${qs({ deep: deep ? "true" : null })}`);

const enc = encodeURIComponent;

/** Encode every segment of a slash-separated path but keep the slashes. */
function encPath(path) {
  return String(path ?? "").split("/").map(enc).join("/");
}

/** Pick only the scope keys ({app, repo}) that carry a value. */
function scopeOf(scope = {}) {
  const out = {};
  if (scope?.app) out.app = scope.app;
  if (scope?.repo) out.repo = scope.repo;
  return out;
}

// Applications (Phase 1 API — see docs/plan `/api/apps` table)
export const getApps = (refresh = false) => req(`/apps${qs({ refresh: refresh ? "true" : null })}`);
export const refreshApps = () => req("/apps/refresh", { method: "POST" });
export const getApp = (name) => req(`/apps/${enc(name)}`);
export const getAppTree = (name, { repo, path } = {}) =>
  req(`/apps/${enc(name)}/tree${qs({ repo, path })}`);
export const getAppFile = (name, repo, path) =>
  req(`/apps/${enc(name)}/files/${enc(repo)}/${encPath(path)}`);
export const getAppWiki = (name, params = {}) => req(`/apps/${enc(name)}/wiki${qs(params)}`);
export const getAppWikiPage = (name, conceptId) =>
  req(`/apps/${enc(name)}/wiki/${enc(conceptId)}`);

// Qdrant
export const getCollections = () => req("/qdrant/collections");
export const getCollection = () => req("/qdrant/collection");
/** params may include: limit, offset, language, file_path, file_prefix, source, app, repo */
export const browsePoints = (params = {}) => req(`/qdrant/points${qs(params)}`);
export const getPoint = (id) => req(`/qdrant/points/${enc(id)}`);

// Graph — `scope` is an optional {app, repo}
export const getGraphStats = (scope = {}) => req(`/graph/stats${qs(scopeOf(scope))}`);
export const getNodes = (label, limit = 50, skip = 0, scope = {}) =>
  req(`/graph/nodes${qs({ label, limit, skip, ...scopeOf(scope) })}`);
export const getSubgraph = (nodeId, depth = 1, limit = 100) =>
  req(`/graph/subgraph${qs({ node_id: nodeId, depth, limit })}`);
export const runCypher = (cypher, params = {}, limit = 100) =>
  req("/graph/cypher", { method: "POST", body: JSON.stringify({ cypher, params, limit }) });

// Semantic search — body may include app, repo, include_wiki, source, top_k (see SearchRequest)
export const searchCode = (body) =>
  req("/search", { method: "POST", body: JSON.stringify(body) });

// Chat
/** {provider, model, configured, reason} — drives the composer's disabled banner. */
export const getChatConfig = () => req("/chat/config");
export const chatSync = (body) =>
  req("/chat", { method: "POST", body: JSON.stringify(body) });

/**
 * Parse one SSE event block (lines already split on "\n") into {event, data}.
 * - comment lines (starting with ":") are ignored (sse-starlette pings)
 * - multiple "data:" lines are joined with "\n" per the SSE spec
 * - one optional leading space after the field colon is stripped
 * Returns null when the block carries no data.
 */
function parseSseBlock(block) {
  let event = "message";
  const dataLines = [];
  for (const rawLine of block.split("\n")) {
    if (!rawLine || rawLine.startsWith(":")) continue;
    const colon = rawLine.indexOf(":");
    const field = colon === -1 ? rawLine : rawLine.slice(0, colon);
    let value = colon === -1 ? "" : rawLine.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value.trim() || "message";
    else if (field === "data") dataLines.push(value);
  }
  if (!dataLines.length) return null;
  return { event, data: dataLines.join("\n") };
}

/**
 * Stream chat over SSE. Calls callbacks:
 *   onStatus(text), onToken(text), onSources(sources), onDone(), onError(text)
 * Returns an AbortController so the caller can stop the stream.
 *
 * The backend (sse-starlette) separates lines with "\r\n"; we normalise to "\n"
 * before splitting so blocks are detected regardless of the line ending used.
 */
export function chatStream(body, { onStatus, onToken, onSources, onDone, onError }) {
  const ctrl = new AbortController();

  const dispatch = (block) => {
    const evt = parseSseBlock(block);
    if (!evt) return;
    let parsed;
    try { parsed = JSON.parse(evt.data); } catch { return; }
    switch (evt.event) {
      case "token":   onToken?.(parsed.text ?? ""); break;
      case "status":  onStatus?.(parsed.text ?? ""); break;
      case "sources": onSources?.(parsed.sources ?? parsed.data ?? []); break;
      case "done":    onDone?.(parsed); break;
      case "error":   onError?.(parsed.text ?? parsed.detail ?? "Unknown error"); break;
      default: break;
    }
  };

  const run = async () => {
    let res;
    try {
      res = await fetch(`${BASE}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
    } catch (e) {
      if (!ctrl.signal.aborted) onError?.(String(e));
      return;
    }
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { const j = await res.json(); detail = j.detail || detail; } catch {}
      onError?.(detail);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        buf = buf.replace(/\r\n?/g, "\n");

        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const block = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          dispatch(block);
        }
      }
      // Flush any trailing block that was not terminated by a blank line.
      buf += decoder.decode();
      buf = buf.replace(/\r\n?/g, "\n");
      if (buf.trim()) dispatch(buf);
    } catch (e) {
      if (!ctrl.signal.aborted) onError?.(String(e));
    }
  };

  run();
  return ctrl;
}
