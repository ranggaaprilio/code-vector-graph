// Application page (#/apps/<name>[/overview|files|wiki]) — Phase 3.
//
// Three tabs share one component:
//   overview  GET /api/apps/{app}                      per-repo cards + aggregates
//   files     GET /api/apps/{app}/tree                 repo -> dir -> file explorer
//             GET /api/apps/{app}/files/{repo}/{path}  file detail (symbols/chunks/wiki)
//   wiki      GET /api/apps/{app}/wiki[/{concept_id}]  OKF pages
//
// Route params: ?repo=<name>&path=<rel path>&concept=<concept_id>.
import { bindLazyView } from "../lib/lazy.js";
import { getApp, getAppTree, getAppFile, getAppWiki, getAppWikiPage } from "../api.js";
import {
  basename,
  dirname,
  breadcrumbs,
  labelColor,
  langHex,
  langBadge,
  langEntries,
  topEntries,
  renderMarkdown,
  highlightWithin,
  hljsLang,
  copyToClipboard,
} from "../lib/format.js";

const TABS = ["overview", "files", "wiki"];
const FILE_RE = /\.[A-Za-z0-9_+-]{1,12}$/;
const WIKI_LIMIT = 300;

export function appView() {
  return {
    // ---- route ------------------------------------------------------------
    name: "",
    tab: "overview",
    repo: "",
    path: "",
    concept: "",

    // ---- overview ---------------------------------------------------------
    detail: null,
    detailLoading: false,
    detailError: null,

    // ---- files ------------------------------------------------------------
    tree: null,            // last /tree response ({kind:"repos"|"dir", ...})
    treeCache: {},         // `${repo} ${dir}` -> response
    treeLoading: false,
    treeError: null,
    dir: "",               // directory currently listed
    file: null,            // /files/... response
    fileLoading: false,
    fileError: null,
    activeSymbol: null,
    activeChunkId: null,
    copiedChunk: null,

    // ---- wiki -------------------------------------------------------------
    wikiPages: [],
    wikiTotal: 0,
    wikiLoading: false,
    wikiError: null,
    wikiFilter: "",
    wikiType: "",
    wikiPage: null,
    wikiPageLoading: false,
    wikiPageError: null,

    _activated: false,
    _stale: false,
    _detailKey: null,
    _wikiKey: null,

    // ---- lifecycle --------------------------------------------------------

    init() {
      this.syncFromRoute();
      this.$watch("$store.app.route", () => {
        this.syncFromRoute();
        if (this.store.screen === "app") this.refresh();
      });
      bindLazyView(this, "app");
    },

    activate() {
      this._activated = true;
      this._stale = false;
      this.syncFromRoute();
      this.refresh();
      this.consumePrefill();
    },

    onScopeChange() {
      const s = this.store;
      if (s.app && this.name && s.app !== this.name) return; // the route will move us
      const repo = s.repo || "";
      if (repo !== this.repo) {
        this.repo = repo;
        this.resetFiles();
        this.wikiPages = [];
        this._wikiKey = null;
      }
      if (s.screen === "app") this.refresh();
      else this._stale = true;
    },

    consumePrefill() { /* the application page is a prefill target, never a consumer */ },

    /** Read `#/apps/<name>/<tab>?repo=&path=&concept=` into local state. */
    syncFromRoute() {
      const route = this.store.route || { segs: [], params: {} };
      const segs = route.segs || [];
      const params = route.params || {};
      this.name = segs[1] || "";
      this.tab = TABS.includes(segs[2]) ? segs[2] : "overview";
      this.repo = params.repo || this.store.repo || "";
      this.path = params.path || "";
      this.concept = params.concept || "";
    },

    /** Load whatever the active tab needs (a no-op when nothing changed). */
    refresh() {
      if (!this.name) return;
      if (this.tab === "overview") this.loadDetail();
      else if (this.tab === "files") this.syncFiles();
      else if (this.tab === "wiki") this.syncWiki();
    },

    // ---- shared -----------------------------------------------------------

    get store() { return this.$store.app; },
    get tabs() { return TABS; },
    get app() {
      return this.detail?.app || this.store.apps.find((a) => a?.name === this.name) || null;
    },
    get repos() { return this.detail?.repos || this.app?.repos || []; },
    get repoInfo() { return this.repos.find((r) => r?.name === this.repo) || null; },

    fmt(n) { return Number(n || 0).toLocaleString(); },
    labelColor(label) { return labelColor(label); },
    langHex(lang) { return langHex(lang); },
    langBadge(lang) { return langBadge(lang); },
    md(text) { return renderMarkdown(text); },
    basename(p) { return basename(p); },

    setTab(tab) {
      if (!this.name || !TABS.includes(tab)) return;
      const params = {};
      if (this.repo) params.repo = this.repo;
      if (tab === "files" && this.path) params.path = this.path;
      if (tab === "wiki" && this.concept) params.concept = this.concept;
      this.store.nav(`/apps/${this.name}/${tab}`, params);
    },

    /** Select a repository (updates the global scope selector too). */
    selectRepo(repoName, { tab } = {}) {
      const target = tab || this.tab;
      this.store.setScope(this.name, repoName || "", { navigate: false });
      this.repo = repoName || "";
      this.resetFiles();
      this.store.nav(`/apps/${this.name}/${target}`, repoName ? { repo: repoName } : {});
    },

    // ---- overview ---------------------------------------------------------

    async loadDetail(force = false) {
      if (!this.name) return;
      if (!force && this._detailKey === this.name && this.detail) return;
      this.detailLoading = true;
      this.detailError = null;
      try {
        this.detail = await getApp(this.name);
        this._detailKey = this.name;
      } catch (e) {
        this.detail = null;
        this.detailError = String(e?.message || e);
      }
      this.detailLoading = false;
    },

    /** [[label, count], ...] for the aggregate label bars. */
    labelBars(limit = 8) {
      const counts = { ...(this.detail?.counts || {}) };
      delete counts.files;
      delete counts.chunks;
      return topEntries(counts, limit).filter(([, v]) => Number(v) > 0);
    },

    maxLabelCount() {
      const bars = this.labelBars();
      return bars.length ? Math.max(1, bars[0][1]) : 1;
    },

    barWidth(count, max) {
      return `${Math.max(2, Math.round((Number(count || 0) / Math.max(1, max)) * 100))}%`;
    },

    /** Language chips: [{lang, count, color}] for the app or one repo. */
    langChips(source) {
      const langs = source ? source.languages : (this.detail?.languages || this.app?.languages);
      return langEntries(langs).map(([lang, count]) => ({ lang, count, color: langHex(lang) }));
    },

    get wikiTop() { return this.detail?.wiki_top || []; },

    /** True when a repo card shows computed stats instead of an OKF overview. */
    isFallback(repo) { return (repo?.overview?.source || "fallback") !== "wiki"; },

    /** Open a repo's top module in the Files tab. */
    openModule(repo, mod) {
      const p = mod?.path && mod.path !== "." ? mod.path : "";
      this.store.setScope(this.name, repo?.name || "", { navigate: false });
      this.store.nav(`/apps/${this.name}/files`, { repo: repo?.name || "", path: p });
    },

    // ---- files ------------------------------------------------------------

    resetFiles() {
      this.tree = null;
      this.treeCache = {};
      this.dir = "";
      this.file = null;
      this.activeSymbol = null;
      this.activeChunkId = null;
      this.fileError = null;
    },

    treeKey(repo, dir) { return `${repo} ${dir}`; },

    /** Reconcile the Files tab with `?repo=&path=`. */
    async syncFiles() {
      if (!this.repo) {
        this.file = null;
        await this.loadTree("", "");
        return;
      }
      const p = this.path || "";
      if (!p) {
        this.file = null;
        await this.loadTree(this.repo, "");
        return;
      }
      const parent = dirname(p) === "" ? "" : dirname(p);
      if (FILE_RE.test(basename(p))) {
        await this.loadTree(this.repo, parent);
        await this.loadFile(p);
        return;
      }
      this.file = null;
      const ok = await this.loadTree(this.repo, p);
      if (!ok) {
        // `path` turned out to be a file after all.
        this.treeError = null;
        await this.loadTree(this.repo, parent);
        await this.loadFile(p);
      }
    },

    /** Fetch (or replay from cache) one tree level. Returns false on failure. */
    async loadTree(repo, dir) {
      const key = this.treeKey(repo, dir);
      const cached = this.treeCache[key];
      if (cached) {
        this.tree = cached;
        this.dir = dir;
        this.treeError = null;
        return true;
      }
      this.treeLoading = true;
      this.treeError = null;
      try {
        const data = await getAppTree(this.name, { repo, path: dir });
        this.treeCache[key] = data;
        this.tree = data;
        this.dir = dir;
        return true;
      } catch (e) {
        this.treeError = String(e?.message || e);
        return false;
      } finally {
        this.treeLoading = false;
      }
    },

    /** Navigate the tree (a directory) — keeps the URL in sync. */
    openDir(dirPath) {
      const params = { repo: this.repo };
      if (dirPath) params.path = dirPath;
      this.store.nav(`/apps/${this.name}/files`, params);
    },

    /** Open a file (the URL carries its repo-relative path). */
    openFile(relPath) {
      this.store.nav(`/apps/${this.name}/files`, { repo: this.repo, path: relPath });
    },

    async loadFile(relPath) {
      if (!relPath || !this.repo) return;
      if (this.file?.file?.rel_path === relPath) return;
      this.fileLoading = true;
      this.fileError = null;
      this.activeSymbol = null;
      this.activeChunkId = null;
      try {
        this.file = await getAppFile(this.name, this.repo, relPath);
        this.$nextTick(() => highlightWithin(this.$refs.chunks));
      } catch (e) {
        this.file = null;
        this.fileError = String(e?.message || e);
      }
      this.fileLoading = false;
    },

    /** `repo / dir / ...` breadcrumb for the tree column. */
    get crumbs() { return breadcrumbs(this.dir); },

    get treeRepos() { return this.tree?.kind === "repos" ? this.tree.repos || [] : []; },
    get treeDirs() { return this.tree?.kind === "dir" ? this.tree.dirs || [] : []; },
    get treeFiles() { return this.tree?.kind === "dir" ? this.tree.files || [] : []; },

    get fileChunks() { return this.file?.chunks || []; },
    get fileSymbols() { return this.file?.symbols || []; },
    get fileWiki() { return this.file?.wiki || []; },
    get fileGlossary() { return this.file?.glossary || []; },

    chunkLabel(c) {
      const s = c?.start_line ?? "?";
      const e = c?.end_line ?? "?";
      return `L${s}–${e}`;
    },

    chunkLang() { return hljsLang(this.file?.file?.language, false); },

    chunkTitle(c) { return c?.function_name || c?.class_name || c?.node_type || ""; },

    /** Select a symbol and scroll to the first chunk that overlaps its lines. */
    focusSymbol(sym) {
      this.activeSymbol = sym || null;
      if (!sym) return;
      const start = Number(sym.start_line || 0);
      const end = Number(sym.end_line || start);
      const hit = this.fileChunks.find(
        (c) => Number(c.end_line ?? 0) >= start && Number(c.start_line ?? 0) <= end,
      );
      this.activeChunkId = hit?.id || null;
      if (!hit) return;
      this.$nextTick(() => {
        document.getElementById(`chunk-${hit.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    },

    async copyChunk(c) {
      const ok = await copyToClipboard(c?.text_content || "");
      if (!ok) return;
      this.copiedChunk = c?.id || null;
      setTimeout(() => { this.copiedChunk = null; }, 2000);
    },

    // ---- cross-view hand-off ----------------------------------------------

    /** Vectors, filtered to this file's chunks. */
    showInVectors() {
      const f = this.file?.file;
      if (!f) return;
      this.store.prefill.vectors = {
        file_path: f.path,
        app: this.name,
        repo: this.repo,
        label: f.rel_path,
      };
      this.store.nav("/vectors", { app: this.name, repo: this.repo });
    },

    /** Graph, focused on this file's node. */
    openInGraph() {
      const f = this.file?.file;
      if (!f) return;
      this.store.prefill.graph = {
        node_id: f.id,
        label: "File",
        caption: f.rel_path || f.path,
        file_path: f.path,
      };
      this.store.nav("/graph", { app: this.name, repo: this.repo });
    },

    /** Chat, with a question about this file pre-typed (never auto-sent). */
    askInChat() {
      const f = this.file?.file;
      if (!f) return;
      const where = f.rel_path || f.path;
      this.store.prefill.chat = {
        text: `Explain what ${where} does in ${this.repo || this.name}.`,
      };
      this.store.nav("/chat", { app: this.name, repo: this.repo });
    },

    // ---- wiki -------------------------------------------------------------

    async syncWiki() {
      if (this.concept) {
        await this.loadWikiPage(this.concept);
        return;
      }
      this.wikiPage = null;
      await this.loadWikiList();
    },

    async loadWikiList(force = false) {
      if (!this.name) return;
      const key = `${this.name}|${this.repo}|${this.wikiType}`;
      if (!force && this._wikiKey === key) return;
      this.wikiLoading = true;
      this.wikiError = null;
      try {
        const data = await getAppWiki(this.name, {
          repo: this.repo || null,
          type: this.wikiType || null,
          limit: WIKI_LIMIT,
        });
        this.wikiPages = data?.pages || [];
        this.wikiTotal = data?.total ?? this.wikiPages.length;
        this._wikiKey = key;
      } catch (e) {
        this.wikiPages = [];
        this.wikiError = String(e?.message || e);
      }
      this.wikiLoading = false;
    },

    async loadWikiPage(conceptId) {
      if (!conceptId) return;
      const cur = this.wikiPage?.page;
      if (cur && (cur.concept_id === conceptId || cur.id === conceptId)) return;
      this.wikiPageLoading = true;
      this.wikiPageError = null;
      try {
        this.wikiPage = await getAppWikiPage(this.name, conceptId);
        this.$nextTick(() => highlightWithin(this.$refs.wikiBody));
      } catch (e) {
        this.wikiPage = null;
        this.wikiPageError = String(e?.message || e);
      }
      this.wikiPageLoading = false;
    },

    /** Open one wiki page (deep-linkable). */
    openWiki(conceptId) {
      if (!conceptId) return;
      const params = { concept: conceptId };
      if (this.repo) params.repo = this.repo;
      this.store.nav(`/apps/${this.name}/wiki`, params);
    },

    backToWikiList() {
      this.store.nav(`/apps/${this.name}/wiki`, this.repo ? { repo: this.repo } : {});
    },

    setWikiType(type) {
      this.wikiType = type || "";
      this.loadWikiList(true);
    },

    get wikiTypes() {
      const seen = new Set();
      for (const p of this.wikiPages) if (p?.type) seen.add(p.type);
      return [...seen].sort();
    },

    get filteredWikiPages() {
      const q = this.wikiFilter.trim().toLowerCase();
      if (!q) return this.wikiPages;
      return this.wikiPages.filter((p) =>
        `${p?.title || ""} ${p?.summary || ""} ${p?.concept_id || ""}`.toLowerCase().includes(q),
      );
    },

    /** [[type, [page, ...]], ...] sorted by type name. */
    get wikiGroups() {
      const groups = {};
      for (const p of this.filteredWikiPages) {
        const t = p?.type || "Other";
        (groups[t] = groups[t] || []).push(p);
      }
      return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
    },

    /** The page's `resource` ("src/a.ts#Symbol") mapped to a Files-tab path when possible. */
    wikiResourcePath(page) {
      const res = page?.resource || "";
      if (!res || /^https?:\/\//i.test(res)) return "";
      return res.split("#")[0];
    },

    openWikiResource(page) {
      const rel = this.wikiResourcePath(page);
      const repo = page?.repo || this.repo || "";
      if (!rel || !repo) return;
      this.store.setScope(this.name, repo, { navigate: false });
      this.store.nav(`/apps/${this.name}/files`, { repo, path: rel });
    },
  };
}
