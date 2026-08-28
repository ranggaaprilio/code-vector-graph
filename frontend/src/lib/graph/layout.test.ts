import { describe, it, expect } from 'vitest';
import { Position } from '@xyflow/svelte';
import { assignLabelLanes, handlePositions, layoutWithElk, NODE_HEIGHT, NODE_WIDTH } from './layout';
import { mergeGraph } from './toFlow';
import type { ApiNode } from './types';

const api = (id: string): ApiNode => ({ id, label: 'Function', caption: id, properties: {} });

describe('handlePositions', () => {
	it('puts handles top/bottom for DOWN and left/right for RIGHT', () => {
		expect(handlePositions('DOWN')).toEqual({
			sourcePosition: Position.Bottom,
			targetPosition: Position.Top
		});
		expect(handlePositions('RIGHT')).toEqual({
			sourcePosition: Position.Right,
			targetPosition: Position.Left
		});
	});
});

describe('layoutWithElk', () => {
	it('returns the input untouched for an empty graph', async () => {
		await expect(layoutWithElk([], [], 'DOWN')).resolves.toEqual([]);
	});

	it('assigns distinct, layered positions and handle sides', async () => {
		const g = mergeGraph({ nodes: [], edges: [] }, [api('a'), api('b'), api('c')], [
			{ from: 'a', to: 'b', type: 'CALLS' },
			{ from: 'a', to: 'c', type: 'CALLS' }
		]);
		const laid = await layoutWithElk(g.nodes, g.edges, 'DOWN');
		expect(laid).toHaveLength(3);
		const byId = Object.fromEntries(laid.map((n) => [n.id, n]));
		// a is the single root, so b and c sit in the layer below it.
		expect(byId.b.position.y).toBeGreaterThanOrEqual(byId.a.position.y + NODE_HEIGHT);
		expect(byId.c.position.y).toBeGreaterThanOrEqual(byId.a.position.y + NODE_HEIGHT);
		// Siblings do not overlap.
		expect(Math.abs(byId.b.position.x - byId.c.position.x)).toBeGreaterThanOrEqual(NODE_WIDTH);
		expect(laid.every((n) => n.sourcePosition === Position.Bottom)).toBe(true);
		// Input array is not mutated.
		expect(g.nodes[0].position).toEqual({ x: 0, y: 0 });
	}, 15000);

	it('lays out left-to-right when asked', async () => {
		const g = mergeGraph({ nodes: [], edges: [] }, [api('a'), api('b')], [{ from: 'a', to: 'b' }]);
		const laid = await layoutWithElk(g.nodes, g.edges, 'RIGHT');
		const byId = Object.fromEntries(laid.map((n) => [n.id, n]));
		expect(byId.b.position.x).toBeGreaterThanOrEqual(byId.a.position.x + NODE_WIDTH);
		expect(byId.a.sourcePosition).toBe(Position.Right);
		expect(byId.b.targetPosition).toBe(Position.Left);
	}, 15000);
});

describe('assignLabelLanes', () => {
	it('gives fan-out siblings consecutive lanes ordered by target position', () => {
		const g = mergeGraph({ nodes: [], edges: [] }, [api('root'), api('l'), api('m'), api('r')], [
			{ from: 'root', to: 'r', type: 'A' },
			{ from: 'root', to: 'l', type: 'B' },
			{ from: 'root', to: 'm', type: 'C' }
		]);
		const placed = g.nodes.map((n) => ({
			...n,
			position: { x: { root: 200, l: 0, m: 200, r: 400 }[n.id] ?? 0, y: n.id === 'root' ? 0 : 100 }
		}));
		const laned = assignLabelLanes(placed, g.edges);
		const lane = (t: string) => (laned.find((e) => e.target === t)?.data as { lane: number }).lane;
		expect([lane('l'), lane('m'), lane('r')]).toEqual([0, 1, 2]);
		// Existing data survives and the input is untouched.
		expect(laned[0].data).toMatchObject({ types: ['A'] });
		expect(g.edges[0].data).not.toHaveProperty('lane');
	});
});
