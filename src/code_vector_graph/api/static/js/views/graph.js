// Graph explorer view
import { getNodes, getSubgraph, runCypher, getGraphStats } from "../api.js";
import { labelColor, copyToClipboard } from "../lib/format.js";

const NODE_LABELS = [
  "File","Module","Class","Interface","TypeAlias","Function","Method",
  "Field","Variable","Import","Chunk","GlossaryEntry",
];

export function graphView() {
  return {
    cy: null,

    // Controls
    selectedLabel: "Function",
    nodeSearch: "",
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

    init() {
      this.$nextTick(() => this.initCytoscape());
    },

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

    async loadLabel() {
      if (!this.selectedLabel) return;
      this.loading = true;
      this.error = null;
      this.statusMsg = `Loading ${this.selectedLabel} nodes…`;
      try {
        const data = await getNodes(this.selectedLabel, 80);
        this.addToCy(data.nodes.map(n => ({
          id: n.id,
          label: this.selectedLabel,
          caption: n.properties.name || n.properties.path || n.id.slice(0, 12),
          properties: n.properties,
          color: labelColor(this.selectedLabel).cy,
        })), []);
        this.statusMsg = `Loaded ${data.nodes.length} ${this.selectedLabel} nodes`;
      } catch (e) {
        this.error = String(e);
      }
      this.loading = false;
    },

    async expandNode(nodeId) {
      this.loading = true;
      this.statusMsg = "Expanding…";
      try {
        const data = await getSubgraph(nodeId, this.depth, 80);
        const nodes = data.nodes.map(n => ({
          id: n.id,
          label: n.label,
          caption: n.caption,
          properties: n.properties,
          color: labelColor(n.label).cy,
        }));
        this.addToCy(nodes, data.edges);
        this.statusMsg = `Expanded: +${data.nodes.length} nodes, +${data.edges.length} edges`;
      } catch (e) {
        this.error = String(e);
      }
      this.loading = false;
    },

    addToCy(nodes, edges) {
      const existingIds = new Set(this.cy.nodes().map(n => n.id()));
      const existingEdgeIds = new Set(this.cy.edges().map(e => e.id()));

      const newElements = [];
      for (const n of nodes) {
        if (!existingIds.has(n.id)) {
          newElements.push({ group: "nodes", data: n });
        }
      }
      for (const e of edges) {
        if (!existingEdgeIds.has(e.id) && existingIds.has(e.from) || !existingIds.has(e.from)) {
          newElements.push({ group: "edges", data: e });
        }
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
        this.cypherError = String(e);
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
  };
}
