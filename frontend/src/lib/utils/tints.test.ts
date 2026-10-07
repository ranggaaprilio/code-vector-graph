// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import {
	RIBBON_TINTS,
	NODE_LABELS,
	tintForIndex,
	tintForLabel,
	tintHex,
	nodeStyle,
	nodeHex,
	nodeShape
} from './tints';

describe('tints', () => {
	it('tintForIndex wraps in both directions', () => {
		expect(tintForIndex(0)).toBe('olive');
		expect(tintForIndex(8)).toBe('olive');
		expect(tintForIndex(-1)).toBe('periwinkle');
	});

	it('tintForLabel is deterministic and always in the closed palette', () => {
		for (const label of ['typescript', 'python', 'Function', 'concept', '']) {
			const t = tintForLabel(label);
			expect(tintForLabel(label)).toBe(t);
			expect(RIBBON_TINTS).toContain(t);
		}
	});

	it('tintHex falls back to the token mirror when the var is unset', () => {
		// jsdom loads no stylesheet, so this exercises the fallback path.
		expect(tintHex('olive')).toBe('#8e8a25');
		expect(tintHex('periwinkle')).toBe('#8c9ae0');
	});

	it('every graph label resolves to a closed tint and an angular shape', () => {
		const angular = ['rectangle', 'diamond', 'triangle', 'hexagon', 'octagon', 'pentagon', 'tag'];
		for (const label of NODE_LABELS) {
			const s = nodeStyle(label);
			expect(RIBBON_TINTS).toContain(s.tint);
			expect(angular).toContain(s.shape);
		}
	});

	it('labels sharing a tint are separated by shape', () => {
		// The containment family is one tint read as a hierarchy of shapes.
		expect(nodeStyle('Application').tint).toBe(nodeStyle('File').tint);
		expect(nodeStyle('Application').shape).not.toBe(nodeStyle('File').shape);
	});

	it('no two labels share both tint and shape', () => {
		const seen = new Set(NODE_LABELS.map((l) => `${nodeStyle(l).tint}/${nodeStyle(l).shape}`));
		expect(seen.size).toBe(NODE_LABELS.length);
	});

	it('unknown labels get the reserved steel fallback', () => {
		expect(nodeStyle('Nonesuch')).toEqual({ tint: 'steel', shape: 'rectangle' });
		expect(nodeHex('Nonesuch')).toBe('#a5b8c0');
		expect(nodeShape('Nonesuch')).toBe('rectangle');
	});

	it('includes the application-level labels', () => {
		for (const label of ['WikiPage', 'Repository', 'Application', 'File', 'Function']) {
			expect(NODE_LABELS).toContain(label);
		}
	});
});
