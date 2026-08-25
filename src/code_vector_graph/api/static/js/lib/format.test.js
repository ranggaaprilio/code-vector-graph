// Run with: node --test src/code_vector_graph/api/static/js/lib/
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  NODE_LABELS,
  LABEL_COLORS,
  basename,
  dirname,
  breadcrumbs,
  relToRoot,
  repoOf,
  hljsLang,
  isWiki,
  locationStr,
  topEntries,
  renderMarkdown,
  highlightWithin,
  escapeHtml,
} from "./format.js";

test("NODE_LABELS includes the new application-level labels", () => {
  for (const label of ["WikiPage", "Repository", "Application", "File", "Function"]) {
    assert.ok(NODE_LABELS.includes(label), `${label} missing`);
    assert.ok(LABEL_COLORS[label].cy.startsWith("#"));
  }
});

test("basename / dirname", () => {
  assert.equal(basename("/a/b/c.ts"), "c.ts");
  assert.equal(basename("c.ts"), "c.ts");
  assert.equal(basename("/a/b/"), "b");
  assert.equal(dirname("/a/b/c.ts"), "/a/b");
  assert.equal(dirname("a/b/c.ts"), "a/b");
  assert.equal(dirname("c.ts"), "");
  assert.equal(dirname("/c.ts"), "/");
});

test("breadcrumbs builds cumulative paths", () => {
  assert.deepEqual(breadcrumbs("src/lib/x.js"), [
    { name: "src", path: "src" },
    { name: "lib", path: "src/lib" },
    { name: "x.js", path: "src/lib/x.js" },
  ]);
  assert.deepEqual(breadcrumbs("/a/b"), [
    { name: "a", path: "/a" },
    { name: "b", path: "/a/b" },
  ]);
  assert.deepEqual(breadcrumbs(""), []);
});

test("relToRoot strips a matching root only", () => {
  assert.equal(relToRoot("/r/onebid/tnlm/src/a.ts", "/r/onebid/tnlm"), "src/a.ts");
  assert.equal(relToRoot("/r/onebid/tnlm/src/a.ts", "/r/onebid/tnlm/"), "src/a.ts");
  assert.equal(relToRoot("/r/onebid/tnlm-extra/src/a.ts", "/r/onebid/tnlm"), "/r/onebid/tnlm-extra/src/a.ts");
  assert.equal(relToRoot("/r/x/a.ts", ""), "/r/x/a.ts");
  assert.equal(relToRoot("/r/x", "/r/x"), "");
});

test("repoOf: explicit wins, then longest root prefix, else null", () => {
  const repos = [
    { name: "outer", root: "/r/onebid" },
    { name: "tnlm", root: "/r/onebid/backend/backend_nodejs_global_tnlm" },
    { name: "sync", root: "/r/onebid/backend/backend_nodejs_data_sync_onebid/" },
  ];
  assert.equal(repoOf("/anything", repos, "recorded"), "recorded");
  assert.equal(repoOf("/r/onebid/backend/backend_nodejs_global_tnlm/src/a.ts", repos), "tnlm");
  assert.equal(repoOf("/r/onebid/backend/backend_nodejs_data_sync_onebid/index.js", repos), "sync");
  assert.equal(repoOf("/r/onebid/backend/other/x.ts", repos), "outer");
  assert.equal(repoOf("/elsewhere/x.ts", repos), null);
  assert.equal(repoOf("", repos), null);
  assert.equal(repoOf("/r/onebid/x.ts", []), null);
});

test("hljsLang maps indexed languages to highlight.js ids", () => {
  assert.equal(hljsLang("typescript"), "typescript");
  assert.equal(hljsLang("tsx"), "typescript");
  assert.equal(hljsLang("javascript"), "javascript");
  assert.equal(hljsLang("jsx"), "javascript");
  assert.equal(hljsLang("python"), "plaintext");
  assert.equal(hljsLang(undefined), "plaintext");
  assert.equal(hljsLang("typescript", true), "markdown");
});

test("isWiki detects wiki payloads", () => {
  assert.equal(isWiki({ source: "wiki" }), true);
  assert.equal(isWiki({ source: "okf_wiki" }), true);
  assert.equal(isWiki({ concept_id: "abc" }), true);
  assert.equal(isWiki({ source: "code" }), false);
  assert.equal(isWiki({}), false);
  assert.equal(isWiki(null), false);
});

test("locationStr", () => {
  assert.equal(locationStr({}), "unknown");
  assert.equal(locationStr({ file_path: "/a/b/c.ts" }), "b/c.ts");
  assert.equal(locationStr({ file_path: "/a/b/c.ts", start_line: 5, end_line: 9 }), "b/c.ts:5-9");
  assert.equal(locationStr({ file_path: "/a/b/c.ts", start_line: 5 }), "b/c.ts:5");
  assert.equal(locationStr({ file_path: "/a/b/c.ts", start_line: 5, end_line: 5 }), "b/c.ts:5");
});

test("topEntries sorts descending and limits", () => {
  const counts = { File: 3, Function: 10, Class: 7 };
  assert.deepEqual(topEntries(counts, 2), [["Function", 10], ["Class", 7]]);
  assert.deepEqual(topEntries(counts), [["Function", 10], ["Class", 7], ["File", 3]]);
  assert.deepEqual(topEntries(null), []);
});

test("renderMarkdown falls back to escaped text without marked/DOMPurify", () => {
  assert.equal(typeof globalThis.marked, "undefined");
  assert.equal(renderMarkdown(""), "");
  assert.equal(renderMarkdown(null), "");
  assert.equal(renderMarkdown("<script>x</script> & \"q\""), escapeHtml("<script>x</script> & \"q\""));
  assert.equal(renderMarkdown("<b>"), "&lt;b&gt;");
});

test("renderMarkdown uses marked + DOMPurify when present", () => {
  globalThis.marked = { parse: (s) => `<p>${s}</p><script>bad()</script>` };
  globalThis.DOMPurify = { sanitize: (h) => h.replace(/<script>.*?<\/script>/g, "") };
  try {
    assert.equal(renderMarkdown("hi"), "<p>hi</p>");
  } finally {
    delete globalThis.marked;
    delete globalThis.DOMPurify;
  }
});

test("highlightWithin is a no-op without hljs or a root element", () => {
  assert.doesNotThrow(() => highlightWithin(null));
  assert.doesNotThrow(() => highlightWithin({ querySelectorAll: () => { throw new Error("should not run"); } }));
});

// ---------------------------------------------------------------------------
// Router / scope helpers
// ---------------------------------------------------------------------------
import {
  parseHash,
  buildHash,
  scopeLabel,
  findRepo,
  explorerTarget,
  langEntries,
  langHex,
  LANG_HEX,
} from "./format.js";

test("parseHash: defaults to apps and keeps the query inside the hash", () => {
  assert.deepEqual(parseHash(""), { view: "apps", segs: ["apps"], params: {} });
  assert.deepEqual(parseHash("#"), { view: "apps", segs: ["apps"], params: {} });
  assert.deepEqual(parseHash("#/"), { view: "apps", segs: ["apps"], params: {} });
  assert.deepEqual(parseHash("#/overview"), { view: "overview", segs: ["overview"], params: {} });
  assert.deepEqual(parseHash("#/apps/onebid/files?repo=x&path=src"), {
    view: "apps",
    segs: ["apps", "onebid", "files"],
    params: { repo: "x", path: "src" },
  });
  assert.deepEqual(parseHash("#/vectors?app=onebid&repo="), {
    view: "vectors",
    segs: ["vectors"],
    params: { app: "onebid", repo: "" },
  });
});

test("parseHash decodes segments and params", () => {
  const r = parseHash("#/apps/my%20app/files?path=src%2Flib%2Fa.ts");
  assert.deepEqual(r.segs, ["apps", "my app", "files"]);
  assert.equal(r.params.path, "src/lib/a.ts");
});

test("buildHash encodes segments and drops empty params", () => {
  assert.equal(buildHash("/apps"), "#/apps");
  assert.equal(buildHash("apps"), "#/apps");
  assert.equal(buildHash("", {}), "#/apps");
  assert.equal(buildHash("/vectors", { app: "onebid", repo: "" }), "#/vectors?app=onebid");
  assert.equal(buildHash("/vectors", { app: null, repo: undefined }), "#/vectors");
  assert.equal(buildHash("/apps/my app/files", { repo: "x", path: "src/a.ts" }), "#/apps/my%20app/files?repo=x&path=src%2Fa.ts");
});

test("parseHash(buildHash(...)) round-trips", () => {
  const hash = buildHash("/apps/onebid/wiki", { concept: "c/1 2", repo: "r" });
  const r = parseHash(hash);
  assert.deepEqual(r.segs, ["apps", "onebid", "wiki"]);
  assert.deepEqual(r.params, { concept: "c/1 2", repo: "r" });
});

test("scopeLabel", () => {
  assert.equal(scopeLabel("", ""), "All applications");
  assert.equal(scopeLabel("onebid", ""), "onebid · all repos");
  assert.equal(scopeLabel("onebid", "backend_nodejs_global_tnlm"), "onebid · backend_nodejs_global_tnlm");
});

const APPS = [
  {
    name: "onebid",
    repos: [
      { name: "tnlm", root: "/r/onebid/backend/backend_nodejs_global_tnlm" },
      { name: "sync", root: "/r/onebid/backend/backend_nodejs_data_sync_onebid" },
    ],
  },
  { name: "other", repos: [{ name: "solo", root: "/r/other" }] },
];

test("findRepo locates a repo across apps", () => {
  assert.equal(findRepo(APPS, "sync").app.name, "onebid");
  assert.equal(findRepo(APPS, "solo").repo.root, "/r/other");
  assert.equal(findRepo(APPS, "nope"), null);
  assert.equal(findRepo([], "sync"), null);
  assert.equal(findRepo(APPS, ""), null);
});

test("explorerTarget resolves repo from payload or path prefix", () => {
  assert.deepEqual(
    explorerTarget(APPS, { file_path: "/r/onebid/backend/backend_nodejs_global_tnlm/src/a.ts" }),
    { app: "onebid", repo: "tnlm", path: "src/a.ts" },
  );
  // recorded repo + rel_path win
  assert.deepEqual(
    explorerTarget(APPS, { file_path: "/whatever/a.ts", repo: "solo", rel_path: "x/a.ts" }),
    { app: "other", repo: "solo", path: "x/a.ts" },
  );
  // unknown repo -> null; recorded but unlisted repo falls back to preferred app
  assert.equal(explorerTarget(APPS, { file_path: "/elsewhere/a.ts" }), null);
  assert.deepEqual(
    explorerTarget(APPS, { file_path: "src/a.ts", repo: "ghost" }, "onebid"),
    { app: "onebid", repo: "ghost", path: "src/a.ts" },
  );
  assert.equal(explorerTarget(APPS, { file_path: "src/a.ts", repo: "ghost" }), null);
  assert.equal(explorerTarget(APPS, null), null);
});

test("langEntries normalises object / array shapes", () => {
  assert.deepEqual(langEntries({ typescript: 5, javascript: 9 }), [["javascript", 9], ["typescript", 5]]);
  assert.deepEqual(langEntries(["typescript", "javascript"]), [["typescript", 0], ["javascript", 0]]);
  assert.deepEqual(langEntries([{ name: "ts", count: 1 }, { language: "js", files: 4 }]), [["js", 4], ["ts", 1]]);
  assert.deepEqual(langEntries(null), []);
  assert.deepEqual(langEntries("typescript"), []);
});

test("langHex has a fallback colour", () => {
  assert.equal(langHex("typescript"), LANG_HEX.typescript);
  assert.equal(langHex("TypeScript"), LANG_HEX.typescript);
  assert.equal(langHex("brainfuck"), "#6b7280");
  assert.equal(langHex(undefined), "#6b7280");
});
