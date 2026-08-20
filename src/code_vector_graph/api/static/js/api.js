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

// Health
export const getHealth = (deep = false) => req(`/health${deep ? "?deep=true" : ""}`);

// Qdrant
export const getCollections = () => req("/qdrant/collections");
export const getCollection = () => req("/qdrant/collection");
export const browsePoints = (params = {}) => {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v != null && q.set(k, v));
  return req(`/qdrant/points?${q}`);
};
export const getPoint = (id) => req(`/qdrant/points/${encodeURIComponent(id)}`);

// Graph
export const getGraphStats = () => req("/graph/stats");
export const getNodes = (label, limit = 50, skip = 0) =>
  req(`/graph/nodes?label=${encodeURIComponent(label)}&limit=${limit}&skip=${skip}`);
export const getSubgraph = (nodeId, depth = 1, limit = 100) =>
  req(`/graph/subgraph?node_id=${encodeURIComponent(nodeId)}&depth=${depth}&limit=${limit}`);
export const runCypher = (cypher, params = {}, limit = 100) =>
  req("/graph/cypher", { method: "POST", body: JSON.stringify({ cypher, params, limit }) });

// Semantic search
export const searchCode = (body) =>
  req("/search", { method: "POST", body: JSON.stringify(body) });

// Chat
export const chatSync = (body) =>
  req("/chat", { method: "POST", body: JSON.stringify(body) });

/**
 * Stream chat over SSE. Calls callbacks:
 *   onStatus(text), onToken(text), onSources(sources), onDone(), onError(text)
 * Returns an AbortController so the caller can stop the stream.
 */
export function chatStream(body, { onStatus, onToken, onSources, onDone, onError }) {
  const ctrl = new AbortController();

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
      onError?.(`${res.status} ${res.statusText}`);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      // Parse SSE lines
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let event = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7).trim();
          else if (line.startsWith("data: ")) data = line.slice(6);
        }
        try {
          const parsed = JSON.parse(data);
          if (event === "token")   onToken?.(parsed.text);
          if (event === "status")  onStatus?.(parsed.text);
          if (event === "sources") onSources?.(parsed.sources);
          if (event === "done")    onDone?.();
          if (event === "error")   onError?.(parsed.text);
        } catch {}
      }
    }
  };

  run();
  return ctrl;
}
