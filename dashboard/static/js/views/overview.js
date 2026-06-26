// Overview / Health view
import { getHealth, getCollection, getGraphStats } from "../api.js";
import { labelColor } from "../lib/format.js";

export function overviewView() {
  return {
    health: null,
    collection: null,
    graphStats: null,
    loading: true,
    error: null,

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      this.error = null;
      try {
        const [h, c, g] = await Promise.all([getHealth(), getCollection(), getGraphStats()]);
        this.health = h;
        this.collection = c;
        this.graphStats = g;
      } catch (e) {
        this.error = String(e);
      }
      this.loading = false;
    },

    statusBadge(ok) {
      return ok
        ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
        : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
    },

    statusDot(ok) {
      return ok ? "bg-green-500" : "bg-red-500";
    },

    labelColor(label) { return labelColor(label); },

    topLabels() {
      if (!this.graphStats?.labels) return [];
      return Object.entries(this.graphStats.labels)
        .filter(([, v]) => v > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 12);
    },

    topRels() {
      if (!this.graphStats?.rel_types) return [];
      return Object.entries(this.graphStats.rel_types)
        .filter(([, v]) => v > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10);
    },

    maxLabelCount() {
      const top = this.topLabels();
      return top.length ? top[0][1] : 1;
    },

    maxRelCount() {
      const top = this.topRels();
      return top.length ? top[0][1] : 1;
    },

    barWidth(count, max) {
      return `${Math.round((count / max) * 100)}%`;
    },
  };
}
