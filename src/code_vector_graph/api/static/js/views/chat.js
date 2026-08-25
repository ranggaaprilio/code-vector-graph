// AI Chat view — provider-agnostic streaming tool loop, scoped to the active
// application/repository.
import { chatStream, getChatConfig } from "../api.js";
import { renderMarkdown, highlightWithin, locationStr, isWiki } from "../lib/format.js";
import { bindLazyView } from "../lib/lazy.js";

const GENERIC_SUGGESTIONS = [
  "How does authentication work in this codebase?",
  "Where is the main entry point and what does it do?",
  "What classes are defined and how do they relate?",
  "Explain the data flow from input to storage.",
];

// Re-render markdown at most this often while tokens are still streaming in —
// keeps the composer responsive without re-parsing on every single token.
const RENDER_THROTTLE_MS = 120;

export function chatView() {
  return {
    messages: [],
    input: "",
    streaming: false,
    streamCtrl: null,
    statusMsg: "",
    sources: [],
    mode: "hybrid",
    topK: 10,
    showOptions: false,
    error: null,

    config: null,
    configLoading: true,

    _activated: false,

    init() {
      bindLazyView(this, "chat");
    },

    activate() {
      if (!this._activated) {
        this._activated = true;
        this.loadConfig();
      }
      this.consumePrefill();
    },

    /** The scope may change mid-conversation; keep history, just note it. */
    onScopeChange() {
      if (!this._activated) return;
      this.messages.push({
        role: "system",
        content: `Scope changed to ${this.store.scopeLabel}.`,
        id: `scope-${Date.now()}`,
      });
      this.scrollToBottom();
    },

    /** A question pre-typed by another view (e.g. Files -> "Ask in Chat"); never auto-sent. */
    consumePrefill() {
      const p = this.store.prefill.chat;
      if (!p) return;
      this.store.prefill.chat = null;
      this.input = p.text || "";
      this.$nextTick(() => this.$refs.composer?.focus());
    },

    get store() { return this.$store.app; },

    async loadConfig() {
      this.configLoading = true;
      try {
        this.config = await getChatConfig();
      } catch (e) {
        this.config = { configured: false, reason: String(e?.message || e) };
      }
      this.configLoading = false;
    },

    get disabledReason() {
      if (this.configLoading) return "";
      if (this.config && this.config.configured === false) {
        return this.config.reason || "Chat is not configured.";
      }
      if (this.store.health?.mcp_session?.ok === false) {
        return "The MCP session is not running — search results are unavailable.";
      }
      return "";
    },

    get suggestions() {
      const app = this.store.currentApp;
      if (!app) return GENERIC_SUGGESTIONS;
      const repos = (app.repos || []).map((r) => r.name);
      const list = [
        `What does the ${app.name} application do?`,
        `Explain the architecture of ${app.name}.`,
        this.store.repo
          ? `What are the main entry points of ${this.store.repo}?`
          : repos.length > 1
            ? `How do ${repos.slice(0, 2).join(" and ")} interact?`
            : `What are the main entry points of ${app.name}?`,
        "What are the main entry points?",
      ];
      return list;
    },

    scrollToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.thread;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    async send() {
      const msg = this.input.trim();
      if (!msg || this.streaming || this.disabledReason) return;
      this.input = "";
      this.error = null;
      this.sources = [];

      this.messages.push({ role: "user", content: msg, id: Date.now() });
      const assistantId = Date.now() + 1;
      this.messages.push({ role: "assistant", content: "", id: assistantId, sources: [], streaming: true });
      this.scrollToBottom();

      this.streaming = true;
      this.statusMsg = "Connecting…";

      const history = this.messages
        .slice(0, -2)
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role, content: m.content }));

      // Always mutate through this.messages (Alpine's reactive proxy) — a
      // closure-captured object reference wouldn't trigger DOM updates.
      const assistantMsg = () => this.messages.find((m) => m.id === assistantId);

      let lastRender = 0;
      const maybeRender = (force) => {
        const now = Date.now();
        if (force || now - lastRender >= RENDER_THROTTLE_MS) {
          lastRender = now;
          this.renderMarkdown(assistantMsg());
        }
      };

      this.streamCtrl = chatStream(
        {
          message: msg,
          history: history.slice(-10),
          options: { mode: this.mode, top_k: this.topK, ...this.store.scopeParams() },
        },
        {
          onStatus: (text) => { this.statusMsg = text; },
          onToken: (text) => {
            const m = assistantMsg();
            m.content += text;
            m.streaming = true;
            maybeRender(false);
            this.scrollToBottom();
          },
          onSources: (srcs) => {
            assistantMsg().sources = srcs || [];
            this.sources = srcs || [];
          },
          onDone: () => {
            assistantMsg().streaming = false;
            this.streaming = false;
            this.statusMsg = "";
            this.streamCtrl = null;
            maybeRender(true);
            this.scrollToBottom();
          },
          onError: (text) => {
            const m = assistantMsg();
            m.content += `\n\n_Error: ${text}_`;
            m.streaming = false;
            this.streaming = false;
            this.statusMsg = "";
            this.error = text;
            this.streamCtrl = null;
            maybeRender(true);
            this.scrollToBottom();
          },
        },
      );
    },

    stop() {
      this.streamCtrl?.abort();
      this.streaming = false;
      this.statusMsg = "";
      const last = this.messages[this.messages.length - 1];
      if (last) last.streaming = false;
    },

    renderMarkdown(msg) {
      msg.renderedHtml = renderMarkdown(msg.content);
      this.$nextTick(() => {
        document.querySelectorAll(".chat-assistant-msg").forEach((el) => highlightWithin(el));
      });
    },

    useSuggestion(s) {
      this.input = s;
      this.$nextTick(() => this.$refs.composer?.focus());
    },

    clearChat() {
      this.messages = [];
      this.sources = [];
      this.error = null;
      this.statusMsg = "";
    },

    onKeydown(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.send();
      }
    },

    locationStr(s) { return locationStr(s); },
    isWiki(s) { return isWiki(s); },

    /** Jump to a source's location in the file explorer, or prefill Vectors if unresolved. */
    openSource(s) {
      if (this.store.openInExplorer(s)) return;
      this.store.prefill.vectors = { file_path: s.file_path };
      this.store.nav("/vectors");
    },
  };
}
