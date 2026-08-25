// Graph explorer view — Cytoscape canvas + read-only Cypher, scoped to the
// active application/repository.
import { getNodes, getSubgraph, runCypher } from "../api.js";
import { labelColor, copyToClipboard, NODE_LABELS, renderMarkdown } from "../lib/format.js";
import { bindLazyView } from "../lib/lazy.js";

export function graphView() {
  return {
    cy: null,

    // Controls
    selectedLabel: "Function",
    depth: 1,

    // Cypher box
    cypherQuery: "MATCH (n:Function) RETURN n LIMIT 25",
    cypherResults: null,
    cypherLoading: false,
    cypherError: null,

    // Inspector panel
    selectedNode: null,

    // Status
    loading: false,
    error: null,
    statusMsg: "",

    labels: NODE_LABELS,

    _activated: false,
    _stale: false,

    init() {
      bindLazyView(this, "graph");
    },

    activate() {
      if (!this._activated) {
        this._activated = true;
        this.$nextTick(() => this.initCytoscape());
      } else if (this._stale) {
        this._stale = false;
        this.cy?.resize();
      }
      this.consumePrefill();
    },

    onScopeChange() {
      if (this.store.screen === "graph") {
        this.clearGraph();
        this.statusMsg = `Scope changed to ${this.store.scopeLabel}`;
      } else {
        this._stale = true;
      }
    },

    /** Focus a specific node handed off from another view (e.g. Files -> "Open in Graph"). */
    async consumePrefill() {
      const p = this.store.prefill.graph;
      if (!p) return;
      this.store.prefill.graph = null;
      if (p.node_id) {
        this.addToCy([{
          id: p.node_id,
          label: p.label || "File",
          caption: p.caption || p.node_id.slice(0, 20),
          properties: { path: p.file_path },
          color: labelColor(p.label || "File").cy,
        }], []);
        await this.expandNode(p.node_id);
        this.cy?.getElementById(p.node_id)?.select();
      }
    },

    get store() { return this.$store.app; },

    initCytoscape() {
      const container = document.getElementById("cy-canvas");
      if (!container) return;

      this.cy = cytoscape({
        container,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "data(color)",
              "label": "data(caption)",
              "color": "#fff",
              "font-size": 10,
              "text-valign": "center",
              "text-halign": "center",
              "width": 40,
              "height": 40,
              "text-wrap": "wrap",
              "text-max-width": 60,
            },
          },
          {
            selector: "edge",
            style: {
              "width": 1.5,
              "line-color": "#6b7280",
              "target-arrow-color": "#6b7280",
              "target-arrow-shape": "triangle",
              "curve-style": "bezier",
              "label": "data(type)",
              "font-size": 8,
              "color": "#9ca3af",
              "text-rotation": "autorotate",
            },
          },
          {
            selector: "node:selected",
            style: { "border-width": 3, "border-color": "#f59e0b" },
          },
        ],
        layout: { name: "cose" },
        wheelSensitivity: 0.3,
      });
      this.cy.resize();

      this.cy.on("tap", "node", (evt) => {
        const node = evt.target;
        this.selectedNode = node.data();
      });

      this.cy.on("dbltap", "node", async (evt) => {
        const node = evt.target;
        const nid = node.data("id");
        await this.expandNode(nid);
      });
    },

    labelColor(label) { return labelColor(label); },
    md(text) { return renderMarkdown(text); },

    async loadLabel() {
      if (!this.selectedLabel) return;
      this.loading = true;
      this.error = null;
      this.statusMsg = `Loading ${this.selectedLabel} nodes…`;
      try {
        const data = await getNodes(this.selectedLabel, 80, 0, this.store.scopeParams());
        this.addToCy(data.nodes.map((n) => ({
          id: n.id,
          label: this.selectedLabel,
          caption: n.properties.name || n.properties.path || n.id.slice(0, 12),
          properties: n.properties,
          color: labelColor(this.selectedLabel).cy,
        })), []);
        this.statusMsg = `Loaded ${data.nodes.length} ${this.selectedLabel} nodes`;
      } catch (e) {
        this.error = String(e?.message || e);
      }
      this.loading = false;
    },

    async expandNode(nodeId) {
      this.loading = true;
      this.statusMsg = "Expanding…";
      try {
        const data = await getSubgraph(nodeId, this.depth, 80);
        const nodes = data.nodes.map((n) => ({
          id: n.id,
          label: n.label,
          caption: n.caption,
          properties: n.properties,
          color: labelColor(n.label).cy,
        }));
        this.addToCy(nodes, data.edges);
        this.statusMsg = `Expanded: +${data.nodes.length} nodes, +${data.edges.length} edges`;
      } catch (e) {
        this.error = String(e?.message || e);
      }
      this.loading = false;
    },

    /**
     * Merge nodes ({id,label,caption,properties,color}) and edges ({id,from,to,type})
     * into the canvas. Edges are only added once both endpoints exist (counting the
     * nodes added in this same batch) and are mapped to Cytoscape's source/target.
     */
    addToCy(nodes, edges) {
      if (!this.cy) return;
      const ids = new Set(this.cy.nodes().map((n) => n.id()));
      const edgeIds = new Set(this.cy.edges().map((e) => e.id()));

      const newElements = [];
      for (const n of nodes || []) {
        if (!n?.id || ids.has(n.id)) continue;
        ids.add(n.id);
        newElements.push({ group: "nodes", data: n });
      }
      for (const e of edges || []) {
        if (!e) continue;
        const source = e.from ?? e.source;
        const target = e.to ?? e.target;
        const id = e.id || `${source}->${e.type || "REL"}->${target}`;
        if (edgeIds.has(id) || !ids.has(source) || !ids.has(target)) continue;
        edgeIds.add(id);
        newElements.push({ group: "edges", data: { id, source, target, type: e.type } });
      }
      if (newElements.length) {
        this.cy.add(newElements);
        this.cy.layout({ name: "cose", animate: true, randomize: false }).run();
      }
    },

    clearGraph() {
      this.cy?.elements().remove();
      this.selectedNode = null;
      this.statusMsg = "Canvas cleared";
    },

    fitGraph() { this.cy?.fit(); },

    async runCypher() {
      this.cypherLoading = true;
      this.cypherError = null;
      this.cypherResults = null;
      try {
        this.cypherResults = await runCypher(this.cypherQuery, {}, 200);
      } catch (e) {
        this.cypherError = String(e?.message || e);
      }
      this.cypherLoading = false;
    },

    async visualizeCypherResults() {
      if (!this.cypherResults) return;
      const nodes = [];
      const edges = [];
      for (const row of this.cypherResults.rows) {
        for (const val of Object.values(row)) {
          if (val && val._type === "node") {
            const label = val._labels?.[0] || "Node";
            nodes.push({
              id: val.id || val._element_id,
              label,
              caption: val.name || val.path || (val.id || "").slice(0, 12),
              properties: val,
              color: labelColor(label).cy,
            });
          } else if (val && val._type === "relationship") {
            edges.push({
              id: val._element_id,
              from: val.start_node_id || "",
              to: val.end_node_id || "",
              type: val._rel_type,
            });
          }
        }
      }
      this.addToCy(nodes, edges);
    },

    async copyNodeId() {
      if (this.selectedNode?.id) await copyToClipboard(this.selectedNode.id);
    },

    nodeProps() {
      if (!this.selectedNode?.properties) return [];
      return Object.entries(this.selectedNode.properties).slice(0, 20);
    },

    formatVal(v) {
      if (Array.isArray(v)) return v.join(", ") || "(empty)";
      if (v === null || v === undefined) return "(null)";
      return String(v);
    },

    /** Explorer / wiki hand-off for the selected node's inspector panel. */
    openSelectedInExplorer() {
      const props = this.selectedNode?.properties;
      if (!props?.path) return;
      this.store.openInExplorer({ file_path: props.path, repo: props.repo, rel_path: props.rel_path });
    },

    openSelectedWikiPage() {
      const props = this.selectedNode?.properties;
      if (!props?.concept_id) return;
      this.store.openWikiPage(props.concept_id, { repo: props.repo });
    },
  };
}
