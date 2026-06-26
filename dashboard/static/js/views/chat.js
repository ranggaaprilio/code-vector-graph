// AI Chat view
import { chatStream } from "../api.js";

const SUGGESTIONS = [
  "How does authentication work in this codebase?",
  "Where is the main entry point and what does it do?",
  "What classes are defined and how do they relate?",
  "Explain the data flow from input to storage.",
];

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
    suggestions: SUGGESTIONS,
    error: null,

    scrollToBottom() {
      this.$nextTick(() => {
        const el = this.$refs.thread;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    async send() {
      const msg = this.input.trim();
      if (!msg || this.streaming) return;
      this.input = "";
      this.error = null;
      this.sources = [];

      this.messages.push({ role: "user", content: msg, id: Date.now() });
      const assistantMsg = { role: "assistant", content: "", id: Date.now() + 1, sources: [], streaming: true };
      this.messages.push(assistantMsg);
      this.scrollToBottom();

      this.streaming = true;
      this.statusMsg = "Connecting…";

      const history = this.messages
        .slice(0, -1)
        .filter(m => m.role !== "system")
        .map(m => ({ role: m.role, content: m.content }));

      this.streamCtrl = chatStream(
        {
          message: msg,
          history: history.slice(-10),
          options: { mode: this.mode, top_k: this.topK },
        },
        {
          onStatus: (text) => {
            this.statusMsg = text;
          },
          onToken: (text) => {
            assistantMsg.content += text;
            assistantMsg.streaming = true;
            this.scrollToBottom();
          },
          onSources: (srcs) => {
            assistantMsg.sources = srcs || [];
            this.sources = srcs || [];
          },
          onDone: () => {
            assistantMsg.streaming = false;
            this.streaming = false;
            this.statusMsg = "";
            this.streamCtrl = null;
            this.renderMarkdown(assistantMsg);
            this.scrollToBottom();
          },
          onError: (text) => {
            assistantMsg.content += `\n\n_Error: ${text}_`;
            assistantMsg.streaming = false;
            this.streaming = false;
            this.statusMsg = "";
            this.error = text;
            this.streamCtrl = null;
            this.scrollToBottom();
          },
        }
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
      if (typeof marked === "undefined" || typeof DOMPurify === "undefined") return;
      msg.renderedHtml = DOMPurify.sanitize(marked.parse(msg.content));
      this.$nextTick(() => {
        document.querySelectorAll(".chat-assistant-msg pre code:not(.hljs)").forEach(el => {
          hljs.highlightElement(el);
        });
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

    locationStr(s) {
      if (!s.file_path) return "";
      const base = s.file_path.split("/").slice(-2).join("/");
      return s.start_line ? `${base}:${s.start_line}` : base;
    },

    openVectors(source) {
      window.location.hash = "#/vectors";
    },
  };
}
