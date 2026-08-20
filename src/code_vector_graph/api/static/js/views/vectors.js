// Vectors / Qdrant browser view
import { browsePoints, searchCode, getPoint } from "../api.js";
import { locationStr, symbolStr, langBadge, copyToClipboard } from "../lib/format.js";

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
    fileFilter: "",

    // Semantic search
    searchQuery: "",
    searchMode: "hybrid",
    searchResults: null,
    searching: false,
    isSearchMode: false,

    // Detail panel
    selectedPoint: null,
    detailLoading: false,

    async init() {
      await this.browse();
    },

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
          file_path: this.fileFilter || null,
        });
        this.points = data.points;
        this.nextOffset = data.next_offset;
      } catch (e) {
        this.error = String(e);
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
          top_k: 20,
          language: this.language || null,
        });
        this.searchResults = data.results;
      } catch (e) {
        this.error = String(e);
      }
      this.searching = false;
    },

    clearSearch() {
      this.searchQuery = "";
      this.isSearchMode = false;
      this.searchResults = null;
      this.browse();
    },

    get displayList() {
      if (this.isSearchMode) {
        return (this.searchResults || []).map(r => ({ id: r.id, payload: r, score: r.score }));
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
      this.$nextTick(() => {
        document.querySelectorAll("pre code[data-highlight]").forEach(el => {
          if (!el.dataset.highlighted) hljs.highlightElement(el);
        });
      });
    },

    async copyCode() {
      const text = this.selectedPoint?.payload?.text_content || "";
      await copyToClipboard(text);
      this.copied = true;
      setTimeout(() => { this.copied = false; }, 2000);
    },

    location(item) { return locationStr(item.payload || item); },
    symbol(item)   { return symbolStr(item.payload || item); },
    langBadge(lang) { return langBadge(lang); },

    chipList(arr) {
      if (!arr || !arr.length) return [];
      return arr.slice(0, 8);
    },
  };
}
