// The 8 closed ribbon-card tints from Design.md. Kept as the only chromatic
// vocabulary for anything that used to be arbitrary hex (language/node-type
// badges, graph nodes) so the palette stays closed per Design.md's Do's/Don'ts.
//
// This file is the one place in the frontend allowed to hold literal hex.
export const RIBBON_TINTS = [
	'olive',
	'sage',
	'salmon',
	'peach',
	'lime',
	'sky',
	'steel',
	'periwinkle'
] as const;

export type Tint = (typeof RIBBON_TINTS)[number];

/** Mirrors --tint-* in styles/tokens.css. Only used when the live CSS custom
 *  property cannot be read (SVG/MiniMap rendering before stylesheets settle). */
const TINT_HEX: Record<Tint, string> = {
	olive: '#fef7d6',
	sage: '#f8f5e8',
	salmon: '#fde0ec',
	peach: '#ffe8d4',
	lime: '#d9f3e1',
	sky: '#dcecfa',
	steel: '#f0eeec',
	periwinkle: '#e6e0f5'
};

/** A few Svelte Flow surfaces take a literal colour through props rather than
 *  CSS (SVG edge markers, the MiniMap's node fill), and derived tokens built
 *  with color-mix() do not resolve through getComputedStyle. So the two
 *  literal anchors of the palette are exported for those call sites. Mirrors
 *  --color-ink / --color-canvas in styles/tokens.css. */
export const INK_HEX = '#1a1a1a';
export const CANVAS_HEX = '#ffffff';

export function tintForIndex(i: number): Tint {
	const n = RIBBON_TINTS.length;
	return RIBBON_TINTS[((i % n) + n) % n];
}

/** Deterministic tint for a label (language name, node type, ...): same label -> same tint every time. */
export function tintForLabel(label: string): Tint {
	let hash = 0;
	for (let i = 0; i < label.length; i++) {
		hash = (hash * 31 + label.charCodeAt(i)) >>> 0;
	}
	return tintForIndex(hash);
}

/** Resolved colour value for a tint. Prefers the live token so the stylesheet
 *  stays the single source of truth; falls back to the mirror above. */
export function tintHex(tint: Tint): string {
	if (typeof document !== 'undefined') {
		const v = getComputedStyle(document.documentElement)
			.getPropertyValue(`--tint-${tint}`)
			.trim();
		if (v) return v;
	}
	return TINT_HEX[tint];
}

// ---------------------------------------------------------------------------
// Graph node vocabulary
//
// 15 Neo4j labels do not fit into 8 tints without collisions, and a graph
// legend where two labels share a swatch is worse than useless. So nodes are
// encoded on two channels: tint (which *family* a node belongs to) and an
// angular shape (which member of the family it is). That keeps the palette
// closed, makes the tint groups actually mean something, and stays readable
// without relying on colour alone.
//
// Shapes are all angular on purpose — Design.md:281 forbids softened corners,
// so no ellipse / round-* shape appears here.
// ---------------------------------------------------------------------------
export const NODE_SHAPES = [
	'rectangle',
	'diamond',
	'triangle',
	'hexagon',
	'octagon',
	'pentagon',
	'tag'
] as const;

export type NodeShape = (typeof NODE_SHAPES)[number];

export type NodeStyle = { tint: Tint; shape: NodeShape };

const NODE_STYLES: Record<string, NodeStyle> = {
	// Containment hierarchy — one tint, three shapes, read as a hierarchy.
	Application: { tint: 'olive', shape: 'octagon' },
	Repository: { tint: 'olive', shape: 'hexagon' },
	File: { tint: 'olive', shape: 'rectangle' },
	// Types
	Class: { tint: 'periwinkle', shape: 'rectangle' },
	Interface: { tint: 'periwinkle', shape: 'diamond' },
	TypeAlias: { tint: 'periwinkle', shape: 'triangle' },
	// Behaviour
	Function: { tint: 'lime', shape: 'rectangle' },
	Method: { tint: 'lime', shape: 'diamond' },
	// Data
	Field: { tint: 'peach', shape: 'rectangle' },
	Variable: { tint: 'peach', shape: 'diamond' },
	// Wiring
	Module: { tint: 'sky', shape: 'hexagon' },
	Import: { tint: 'sky', shape: 'tag' },
	// Content
	Chunk: { tint: 'sage', shape: 'rectangle' },
	WikiPage: { tint: 'salmon', shape: 'rectangle' },
	GlossaryEntry: { tint: 'salmon', shape: 'pentagon' }
};

const UNKNOWN_NODE: NodeStyle = { tint: 'steel', shape: 'rectangle' };

/** Browsable Neo4j labels, in legend order. */
export const NODE_LABELS = Object.keys(NODE_STYLES);

export function nodeStyle(label: string): NodeStyle {
	return NODE_STYLES[label] ?? UNKNOWN_NODE;
}

/** Resolved fill colour for a graph node — for the places that cannot take a
 *  var() reference (SVG markers, MiniMap nodeColor). DOM nodes should use
 *  nodeTintVar() so the stylesheet stays the single source of truth. */
export function nodeHex(label: string): string {
	return tintHex(nodeStyle(label).tint);
}

/** CSS var() reference for a graph node's tint, for DOM-rendered surfaces
 *  (Svelte Flow nodes, legend swatches, inspector). */
export function nodeTintVar(label: string): string {
	return `var(--tint-${nodeStyle(label).tint})`;
}

export function nodeShape(label: string): NodeShape {
	return nodeStyle(label).shape;
}
