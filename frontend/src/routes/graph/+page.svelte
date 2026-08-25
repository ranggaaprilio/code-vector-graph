<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { page as pageState } from '$app/state';
	import cytoscape from 'cytoscape';
	import { SectionEyebrow, Button, Select, TextArea, DataTable } from '$lib/components/ds';
	import { appStore } from '$lib/stores/app.svelte';
	import { getNodes, getSubgraph, runCypher as apiRunCypher } from '$lib/api/client';
	import { renderMarkdown, copyToClipboard } from '$lib/utils/format';
	import { NODE_LABELS, NODE_SHAPES, nodeHex, nodeShape, INK_HEX } from '$lib/utils/tints';

	type CyCore = cytoscape.Core;

	type GraphNode = {
		id: string;
		label: string;
		caption: string;
		properties: Record<string, unknown>;
		color: string;
		shape: string;
	};
	type GraphEdge = {
		id?: string;
		from?: string;
		to?: string;
		source?: string;
		target?: string;
		type?: string;
	};

	type CypherResults = { columns: string[]; rows: Record<string, unknown>[]; truncated: boolean };

	let canvasEl: HTMLDivElement | undefined = $state();
	let cy: CyCore | null = null;

	// Controls
	let selectedLabel = $state(NODE_LABELS.includes('Function') ? 'Function' : NODE_LABELS[0]);
	let depthStr = $state('1');

	// Status
	let loading = $state(false);
	let error = $state<string | null>(null);
	let statusMsg = $state('');

	// Inspector
	let selectedNode = $state<GraphNode | null>(null);

	// Cypher box
	let cypherQuery = $state('MATCH (n:Function) RETURN n LIMIT 25');
	let cypherResults = $state<CypherResults | null>(null);
	let cypherLoading = $state(false);
	let cypherError = $state<string | null>(null);

	/** Cypher rows flattened to display strings, mirroring the old dashboard's
	 *  best-effort object -> label rendering (name / labels / truncated JSON). */
	const cypherColumns = $derived(
		(cypherResults?.columns ?? []).map((c) => ({ key: c, label: c }))
	);
	const cypherRows = $derived(
		(cypherResults?.rows ?? []).slice(0, 50).map((row) => {
			const out: Record<string, string> = {};
			for (const col of cypherResults?.columns ?? []) {
				const v = row[col];
				if (v && typeof v === 'object') {
					const obj = v as Record<string, unknown>;
					const labels = obj._labels;
					out[col] =
						(obj.name as string) ||
						(Array.isArray(labels) ? labels.join(':') : '') ||
						JSON.stringify(obj).slice(0, 30);
				} else {
					out[col] = String(v ?? '');
				}
			}
			return out;
		})
	);

	onMount(() => {
		if (!canvasEl) return;
		cy = cytoscape({
			container: canvasEl,
			style: [
				{
					// Nodes are catalog tints inside a hairline, like every other
					// surface in this design system. Shape carries the label so the
					// legend never relies on colour alone.
					selector: 'node',
					style: {
						'background-color': 'data(color)',
						'border-width': 1,
						'border-color': INK_HEX,
						label: 'data(caption)',
						color: INK_HEX,
						'font-family': 'Helvetica, Arial, sans-serif',
						'font-size': 10,
						'text-valign': 'center',
						'text-halign': 'center',
						width: 44,
						height: 44,
						'text-wrap': 'wrap',
						'text-max-width': '60px'
					}
				},
				// One rule per shape: cytoscape's types don't model a data() mapper
				// for `shape`, and this stays type-safe.
				...NODE_SHAPES.map((sh) => ({
					selector: `node[shape="${sh}"]`,
					style: { shape: sh }
				})),
				{
					selector: 'edge',
					style: {
						width: 1,
						'line-color': INK_HEX,
						'target-arrow-color': INK_HEX,
						'target-arrow-shape': 'triangle',
						'curve-style': 'bezier',
						label: 'data(type)',
						'font-family': 'Helvetica, Arial, sans-serif',
						'font-size': 8,
						color: INK_HEX,
						'text-rotation': 'autorotate'
					}
				},
				{
					// Selection thickens the edge — the same motif the cards use.
					selector: 'node:selected',
					style: { 'border-width': 4, 'border-color': INK_HEX }
				}
			],
			layout: { name: 'cose' },
			wheelSensitivity: 0.3
		});

		cy.on('tap', 'node', (evt) => {
			selectedNode = evt.target.data() as GraphNode;
		});

		cy.on('dbltap', 'node', async (evt) => {
			await expandNode(evt.target.data('id'));
		});

		// Hand-off from the file explorer arrives as ?node=<graph node id>.
		const handOffNode = pageState.url.searchParams.get('node');
		if (handOffNode) {
			void expandNode(handOffNode);
		}

		return () => {
			cy?.destroy();
			cy = null;
		};
	});

	// Scope changes used to refetch the visible view (js/lib/lazy.js). Only
	// reload if something is already on the canvas — an empty canvas has nothing
	// to go stale.
	let seenScope = appStore.scopeVersion;
	$effect(() => {
		const v = appStore.scopeVersion;
		if (v === seenScope) return;
		seenScope = v;
		untrack(() => {
			if (!cy || cy.nodes().length === 0) return;
			clearGraph();
			void loadLabel();
		});
	});

	/**
	 * Merge nodes/edges into the canvas. Edges are only added once both endpoints
	 * exist (counting nodes added in this same batch) and are mapped to
	 * Cytoscape's source/target.
	 */
	function addToCy(nodes: GraphNode[], edges: GraphEdge[]) {
		if (!cy) return;
		const ids = new Set(cy.nodes().map((n) => n.id()));
		const edgeIds = new Set(cy.edges().map((e) => e.id()));

		const newElements: cytoscape.ElementDefinition[] = [];
		for (const n of nodes || []) {
			if (!n?.id || ids.has(n.id)) continue;
			ids.add(n.id);
			newElements.push({ group: 'nodes', data: n });
		}
		for (const e of edges || []) {
			if (!e) continue;
			const source = e.from ?? e.source ?? '';
			const target = e.to ?? e.target ?? '';
			const id = e.id || `${source}->${e.type || 'REL'}->${target}`;
			if (edgeIds.has(id) || !ids.has(source) || !ids.has(target)) continue;
			edgeIds.add(id);
			newElements.push({ group: 'edges', data: { id, source, target, type: e.type } });
		}
		if (newElements.length) {
			cy.add(newElements);
			cy.layout({ name: 'cose', animate: true, randomize: false }).run();
		}
	}

	async function loadLabel() {
		if (!selectedLabel) return;
		loading = true;
		error = null;
		statusMsg = `Loading ${selectedLabel} nodes…`;
		try {
			const data = (await getNodes(selectedLabel, 80, 0, appStore.scopeParams())) as {
				nodes: { id: string; properties: Record<string, unknown> }[];
			};
			const nodes: GraphNode[] = data.nodes.map((n) => ({
				id: n.id,
				label: selectedLabel,
				caption: String(n.properties.name || n.properties.path || n.id.slice(0, 12)),
				properties: n.properties,
				color: nodeHex(selectedLabel),
				shape: nodeShape(selectedLabel)
			}));
			addToCy(nodes, []);
			statusMsg = `Loaded ${data.nodes.length} ${selectedLabel} nodes`;
		} catch (e) {
			error = String((e as Error)?.message || e);
		}
		loading = false;
	}

	async function expandNode(nodeId: string) {
		loading = true;
		statusMsg = 'Expanding…';
		try {
			const data = (await getSubgraph(nodeId, Number(depthStr), 80)) as {
				nodes: GraphNode[];
				edges: GraphEdge[];
			};
			const nodes = data.nodes.map((n) => ({
				...n,
				color: nodeHex(n.label),
				shape: nodeShape(n.label)
			}));
			addToCy(nodes, data.edges);
			// Reflect the expansion in the inspector so a hand-off lands on the
			// node the user actually asked for, not on an empty panel.
			const hit = nodes.find((n) => n.id === nodeId);
			if (hit) {
				selectedNode = hit;
				cy?.$id(nodeId).select();
			}
			statusMsg = `Expanded: +${data.nodes.length} nodes, +${data.edges.length} edges`;
		} catch (e) {
			error = String((e as Error)?.message || e);
		}
		loading = false;
	}

	function clearGraph() {
		cy?.elements().remove();
		selectedNode = null;
		statusMsg = 'Canvas cleared';
	}

	function fitGraph() {
		cy?.fit();
	}

	async function handleRunCypher() {
		cypherLoading = true;
		cypherError = null;
		cypherResults = null;
		try {
			cypherResults = (await apiRunCypher(cypherQuery, {}, 200)) as CypherResults;
		} catch (e) {
			cypherError = String((e as Error)?.message || e);
		}
		cypherLoading = false;
	}

	function visualizeCypherResults() {
		if (!cypherResults) return;
		const nodes: GraphNode[] = [];
		const edges: GraphEdge[] = [];
		for (const row of cypherResults.rows) {
			for (const val of Object.values(row)) {
				if (val && typeof val === 'object') {
					const obj = val as Record<string, unknown>;
					if (obj._type === 'node') {
						const labels = obj._labels as string[] | undefined;
						const label = labels?.[0] || 'Node';
						const id = String(obj.id || obj._element_id || '');
						nodes.push({
							id,
							label,
							caption: String(obj.name || obj.path || id.slice(0, 12)),
							properties: obj,
							color: nodeHex(label),
							shape: nodeShape(label)
						});
					} else if (obj._type === 'relationship') {
						edges.push({
							id: String(obj._element_id || ''),
							from: String(obj.start_node_id || ''),
							to: String(obj.end_node_id || ''),
							type: obj._rel_type as string | undefined
						});
					}
				}
			}
		}
		addToCy(nodes, edges);
	}

	async function copyNodeId() {
		if (selectedNode?.id) await copyToClipboard(selectedNode.id);
	}

	function nodeProps(): [string, unknown][] {
		if (!selectedNode?.properties) return [];
		return Object.entries(selectedNode.properties).slice(0, 20);
	}

	function formatVal(v: unknown): string {
		if (Array.isArray(v)) return v.join(', ') || '(empty)';
		if (v === null || v === undefined) return '(null)';
		return String(v);
	}

	function openSelectedInExplorer() {
		const props = selectedNode?.properties;
		const path = props?.path as string | undefined;
		if (!path) return;
		appStore.openInExplorer({
			file_path: path,
			repo: props?.repo as string | undefined,
			rel_path: props?.rel_path as string | undefined
		});
	}

	function openSelectedWikiPage() {
		const props = selectedNode?.properties;
		const conceptId = props?.concept_id as string | undefined;
		if (!conceptId) return;
		appStore.openWikiPage(conceptId, { repo: props?.repo as string | undefined });
	}
</script>

<SectionEyebrow title="GRAPH EXPLORER" tint="periwinkle" />

<div class="graph-page">
	<div class="controls">
		<Select bind:value={selectedLabel}>
			{#each NODE_LABELS as l (l)}
				<option value={l}>{l}</option>
			{/each}
		</Select>
		<Button variant="primary" onclick={loadLabel} disabled={loading}>Load nodes</Button>

		<Select bind:value={depthStr}>
			<option value="1">Depth 1</option>
			<option value="2">Depth 2</option>
			<option value="3">Depth 3</option>
		</Select>

		<span class="ds-caption scope-readout">Scope: {appStore.scopeLabelText}</span>

		<div class="spacer"></div>

		<Button variant="secondary" onclick={fitGraph}>Fit</Button>
		<Button variant="secondary" onclick={clearGraph}>Clear</Button>

		{#if statusMsg}
			<span class="ds-caption status-msg">{statusMsg}</span>
		{/if}
		{#if error}
			<span class="ds-caption error-msg">{error}</span>
		{/if}
	</div>

	<div class="legend">
		{#each NODE_LABELS as l (l)}
			<span class="legend-item ds-caption">
				<span class="ds-swatch" data-shape={nodeShape(l)} style="background:{nodeHex(l)}"></span>
				{l}
			</span>
		{/each}
	</div>

	<div class="workspace">
		<div class="canvas-panel">
			<div class="canvas" bind:this={canvasEl}></div>
			{#if loading}
				<div class="canvas-loading ds-caption">Loading…</div>
			{/if}
			<div class="canvas-hint ds-caption">Double-click a node to expand</div>
		</div>

		<div class="side-panel">
			<div class="inspector">
				<h3 class="ds-ui-label">Node Inspector</h3>
				{#if !selectedNode}
					<p class="ds-caption">Click a node</p>
				{:else}
					<div class="inspector-header">
						<span
							class="ds-swatch"
							data-shape={nodeShape(selectedNode.label)}
							style="background:{nodeHex(selectedNode.label)}"
						></span>
						<span class="ds-ui-label">{selectedNode.label}</span>
						<Button variant="text-link" class="copy-btn" onclick={copyNodeId}>copy id</Button>
					</div>
					<div class="ds-body-sm caption">{selectedNode.caption}</div>

					{#if selectedNode.label === 'WikiPage'}
						<div class="wiki-preview">
							{@html renderMarkdown(
								String(selectedNode.properties?.summary || selectedNode.properties?.overview || '')
							)}
							<Button variant="secondary" onclick={openSelectedWikiPage}>Open wiki page</Button>
						</div>
					{:else if selectedNode.label === 'File'}
						<Button variant="secondary" onclick={openSelectedInExplorer}>Open in Explorer</Button>
					{/if}

					<div class="props">
						{#each nodeProps() as [k, v] (k)}
							<div class="prop-row">
								<span class="ds-caption prop-key">{k}</span>
								<span class="ds-body-sm prop-val">{formatVal(v)}</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<div class="cypher-box">
				<h3 class="ds-ui-label">Read-only Cypher</h3>
				<TextArea bind:value={cypherQuery} rows={5} placeholder="MATCH (n:Function) RETURN n LIMIT 25" class="cypher-input" />
				<div class="cypher-actions">
					<Button variant="primary" onclick={handleRunCypher} disabled={cypherLoading}>
						{cypherLoading ? '…' : 'Run'}
					</Button>
					{#if cypherResults?.rows?.length}
						<Button variant="secondary" onclick={visualizeCypherResults}>Visualize</Button>
					{/if}
				</div>
				{#if cypherError}
					<div class="ds-caption error-msg cypher-error">{cypherError}</div>
				{/if}
				{#if cypherResults && !cypherError}
					<div class="cypher-results">
						<DataTable columns={cypherColumns} rows={cypherRows} />
						{#if cypherResults.truncated}
							<div class="ds-caption truncated-msg">Results truncated</div>
						{/if}
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.graph-page {
		display: flex;
		flex-direction: column;
		height: 100%;
	}

	.controls {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-md);
		border-bottom: var(--border-hairline);
	}

	.controls :global(select) {
		width: auto;
	}

	.spacer {
		flex: 1;
	}

	.scope-readout {
		color: var(--color-ink-muted);
	}

	.status-msg {
		color: var(--color-link);
	}

	.error-msg {
		color: var(--color-primary);
	}

	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-md);
		padding: var(--space-s) var(--space-md);
		border-bottom: var(--border-hairline);
	}

	.legend-item {
		display: inline-flex;
		align-items: center;
		gap: var(--space-xs);
		color: var(--color-ink-muted);
	}

	.workspace {
		flex: 1;
		display: flex;
		min-height: 560px;
	}

	.canvas-panel {
		position: relative;
		flex: 1;
		min-width: 0;
		border: 1px solid var(--color-frame-ink);
		background: var(--color-canvas);
	}

	.canvas {
		position: absolute;
		inset: 0;
	}

	.canvas-loading,
	.canvas-hint {
		position: absolute;
		background: var(--color-canvas);
		border: var(--border-hairline);
		padding: var(--space-xxs) var(--space-xs);
	}

	.canvas-loading {
		top: var(--space-sm);
		left: var(--space-sm);
	}

	.canvas-hint {
		bottom: var(--space-sm);
		left: var(--space-sm);
		color: var(--color-ink-muted);
	}

	.side-panel {
		width: 320px;
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		border-left: none;
		border-top: 1px solid var(--color-frame-ink);
		border-right: 1px solid var(--color-frame-ink);
		border-bottom: 1px solid var(--color-frame-ink);
	}

	.inspector {
		padding: var(--space-md);
		border-bottom: var(--border-hairline);
		max-height: 50%;
		overflow-y: auto;
	}

	.inspector-header {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		margin-top: var(--space-sm);
	}

	.inspector-header :global(.copy-btn) {
		margin-left: auto;
	}

	.caption {
		margin-top: var(--space-xs);
		font-weight: 700;
		word-break: break-all;
	}

	.wiki-preview {
		margin-top: var(--space-sm);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.wiki-preview :global(*) {
		font-size: var(--type-body-sm-size);
	}

	.props {
		margin-top: var(--space-sm);
		display: flex;
		flex-direction: column;
		gap: var(--space-xxs);
	}

	.prop-row {
		display: flex;
		gap: var(--space-xs);
	}

	.prop-key {
		width: 84px;
		flex-shrink: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.prop-val {
		word-break: break-all;
	}

	.cypher-box {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-height: 0;
		padding: var(--space-md);
		gap: var(--space-sm);
		overflow-y: auto;
	}

	.cypher-box :global(.cypher-input) {
		font-family: var(--font-mono);
		font-size: var(--type-body-sm-size);
		flex-shrink: 0;
	}

	.cypher-actions {
		display: flex;
		gap: var(--space-sm);
	}

	.cypher-error {
		word-break: break-word;
	}

	.cypher-results {
		max-height: 220px;
		overflow: auto;
	}

	.truncated-msg {
		margin-top: var(--space-xs);
		color: var(--tint-peach);
	}

	@media (max-width: 900px) {
		.workspace {
			flex-direction: column;
		}
		.side-panel {
			width: auto;
		}
	}
</style>
