// Main Alpine app — router, health store, theme
import { overviewView } from "./views/overview.js";
import { vectorsView  } from "./views/vectors.js";
import { graphView    } from "./views/graph.js";
import { chatView     } from "./views/chat.js";
import { getHealth    } from "./api.js";

// Register all views as Alpine components
document.addEventListener("alpine:init", () => {
  Alpine.data("overviewView", overviewView);
  Alpine.data("vectorsView",  vectorsView);
  Alpine.data("graphView",    graphView);
  Alpine.data("chatView",     chatView);

  // Global app store
  Alpine.store("app", {
    view: "overview",
    dark: localStorage.getItem("dark") === "true",
    health: { qdrant: { ok: null }, neo4j: { ok: null }, mcp_session: { ok: null } },
    healthLoaded: false,

    init() {
      this.applyTheme();
      this.syncRoute();
      window.addEventListener("hashchange", () => this.syncRoute());
      this.pollHealth();
    },

    syncRoute() {
      const hash = (location.hash || "#/overview").slice(2) || "overview";
      this.view = hash;
    },

    nav(view) {
      this.view = view;
      location.hash = `#/${view}`;
    },

    toggleDark() {
      this.dark = !this.dark;
      localStorage.setItem("dark", this.dark);
      this.applyTheme();
    },

    applyTheme() {
      document.documentElement.classList.toggle("dark", this.dark);
    },

    async pollHealth() {
      try {
        this.health = await getHealth(false);
        this.healthLoaded = true;
      } catch { this.healthLoaded = true; }
      setTimeout(() => this.pollHealth(), 30_000);
    },

    statusDot(ok) {
      if (ok === null) return "bg-gray-400";
      return ok ? "bg-green-500" : "bg-red-500";
    },
  });
});
