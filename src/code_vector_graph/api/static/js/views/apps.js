// Applications list view (#/apps) — one card per indexed application.
import { bindLazyView } from "../lib/lazy.js";
import { langEntries, langHex } from "../lib/format.js";

export function appsView() {
  return {
    filter: "",
    refreshing: false,
    _activated: false,

    init() {
      bindLazyView(this, "apps");
    },

    activate() {
      if (!this._activated) {
        this._activated = true;
        // The store already kicked off loadApps(); only retry after a failure.
        const store = this.$store.app;
        if (!store.appsLoaded && store.appsError) store.loadApps();
      }
      this.consumePrefill();
    },

    onScopeChange() { /* the list is scope-independent */ },
    consumePrefill() { /* nothing to prefill on the list */ },

    get store() { return this.$store.app; },
    get loading() { return !this.store.appsLoaded && !this.store.appsError && !this.refreshing; },

    get filtered() {
      const q = this.filter.trim().toLowerCase();
      const apps = this.store.apps || [];
      if (!q) return apps;
      return apps.filter((a) =>
        String(a?.name || "").toLowerCase().includes(q) ||
        (a?.repos || []).some((r) => String(r?.name || "").toLowerCase().includes(q)),
      );
    },

    async refresh() {
      this.refreshing = true;
      try { await this.store.loadApps(true); } finally { this.refreshing = false; }
    },

    open(app) {
      if (!app?.name) return;
      this.store.nav(`/apps/${app.name}`);
    },

    /** Jump straight into one repository's file explorer. */
    openRepo(app, repo) {
      if (!app?.name || !repo?.name) return;
      this.store.setScope(app.name, repo.name, { navigate: false });
      this.store.nav(`/apps/${app.name}/files`, { repo: repo.name });
    },

    /** [{lang, count, pct, color}] for the stacked language bar. */
    langBar(app) {
      const entries = langEntries(app?.languages);
      const total = entries.reduce((s, [, c]) => s + (c || 0), 0);
      return entries.map(([lang, count]) => ({
        lang,
        count,
        pct: total ? Math.max(2, Math.round((count / total) * 100)) : Math.round(100 / (entries.length || 1)),
        color: langHex(lang),
      }));
    },

    repoNames(app) { return (app?.repos || []).map((r) => r?.name).filter(Boolean); },
    isDerived(app) { return app?.source === "derived" || (app?.repos || []).some((r) => r?.source === "derived"); },
    fmt(n) { return Number(n || 0).toLocaleString(); },
  };
}
