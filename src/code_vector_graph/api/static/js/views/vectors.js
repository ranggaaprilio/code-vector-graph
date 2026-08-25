// Vectors / Qdrant browser view — semantic search + raw payload browse, scoped
// to the active application/repository.
import { browsePoints, getPoint, searchCode } from "../api.js";
import { bindLazyView } from "../lib/lazy.js";
import {
  locationStr,
  symbolStr,
  langBadge,
  hljsLang,
  isWiki,
  repoOf,
  renderMarkdown,
  highlightWithin,
} from "../lib/format.js";

const TOP_K_OPTIONS = [10, 20, 50];

export function vectorsView() {
  return {
    // Browse state
    points: [],
    nextOffset: null,
    prevOffsets: [],
    loading: false,
    error: null,

    // Filters
    language: "",
    filePrefix: "",
    topK: 20,

    // Semantic search
    searchQuery: "",
    searchMode: "hybrid",
    searchResults: null,
    searching: false,
    isSearchMode: false,

    // Detail panel
    selectedPoint: null,

    _activated: false,
    _stale: false,

    topKOptions: TOP_K_OPTIONS,

    init() {
      bindLazyView(this, "vectors");
    },

    activate() {
      if (!this._activated || this._stale) {
        this._activated = true;
        this._stale = false;
        this.isSearchMode ? this.search() : this.browse();
      }
      this.consumePrefill();
    },

    onScopeChange() {
      if (this.store.screen === "vectors") {
        this.prevOffsets = [];
        this.isSearchMode ? this.search() : this.browse();
      } else {
        this._stale = true;
      }
    },

    /** A file the caller wants highlighted, handed off from the Files tab. */
    consumePrefill() {
      const p = this.store.prefill.vectors;
      if (!p) return;
      this.store.prefill.vectors = null;
      this.clearSearch();
      this.filePrefix = p.file_path || "";
      this.browse().then(() => {
        const hit = this.points.find((pt) => pt.payload?.file_path === p.file_path);
        if (hit) this.selectPoint(hit.id, hit.payload);
      });
    },

    get store() { return this.$store.app; },

    async browse(offset = null) {
      this.loading = true;
      this.error = null;
      this.isSearchMode = false;
      this.searchResults = null;
      try {
        const data = await browsePoints({
          limit: 50,
          offset,
          language: this.language || null,
          file_prefix: this.filePrefix || null,
          ...this.store.scopeParams(),
        });
        this.points = data.points;
        this.nextOffset = data.next_offset;
      } catch (e) {
        this.error = String(e?.message || e);
      }
      this.loading = false;
    },

    async search() {
      if (!this.searchQuery.trim()) { await this.browse(); return; }
      this.searching = true;
      this.error = null;
      this.isSearchMode = true;
      try {
        const data = await searchCode({
          query: this.searchQuery,
          mode: this.searchMode,
          top_k: this.topK,
          language: this.language || null,
          include_wiki: true,
          ...this.store.scopeParams(),
        });
        this.searchResults = data.results;
      } catch (e) {
        this.error = String(e?.message || e);
      }
      this.searching = false;
    },

    clearSearch() {
      this.searchQuery = "";
      this.isSearchMode = false;
      this.searchResults = null;
      this.selectedPoint = null;
    },

    get displayList() {
      if (this.isSearchMode) {
        return (this.searchResults || []).map((r) => ({ id: r.id, payload: r, score: r.score }));
      }
      return this.points;
    },

    async nextPage() {
      if (!this.nextOffset) return;
      this.prevOffsets.push(null); // track for back
      await this.browse(this.nextOffset);
    },

    async prevPage() {
      const offset = this.prevOffsets.pop() || null;
      await this.browse(offset);
    },

    async selectPoint(id, payload) {
      if (this.selectedPoint?.id === id) { this.selectedPoint = null; return; }
      this.selectedPoint = { id, payload };
      this.$nextTick(() => highlightWithin(this.$refs.detail));
    },

    /** Try to fetch the full payload for a point that only carries a summary. */
    async loadFullPoint(id) {
      try {
        const data = await getPoint(id);
        if (this.selectedPoint?.id === id) this.selectedPoint = { id, payload: data.payload };
      } catch { /* keep what we already have */ }
    },

    location(item) { return locationStr(item.payload || item); },
    symbol(item)   { return symbolStr(item.payload || item); },
    langBadge(lang) { return langBadge(lang); },
    hljsLang(lang, wiki = false) { return hljsLang(lang, wiki); },
    isWiki(item)   { return isWiki(item?.payload || item); },
    md(text) { return renderMarkdown(text); },

    /** App/repo badge shown next to a result when the scope is "All" or app-wide. */
    repoLabel(item) {
      const p = item?.payload || item;
      const name = p?.repo || repoOf(p?.file_path, this.store.allRepos, p?.repo);
      return name && (!this.store.repo || this.store.repo !== name) ? name : "";
    },

    /** Explorer deep link for the selected point, or null when the repo is unknown. */
    explorerTarget(item) {
      return this.store.explorerTarget(item?.payload || item);
    },

    openInExplorer(item) {
      this.store.openInExplorer(item?.payload || item);
    },

    chipList(arr) {
      if (!arr || !arr.length) return [];
      return arr.slice(0, 8);
    },
  };
}
