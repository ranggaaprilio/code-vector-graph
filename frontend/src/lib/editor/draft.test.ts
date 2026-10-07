import { describe, expect, it } from 'vitest';
import { clearDraft, loadDraft, saveDraft, type DraftStorage } from './draft';

function fakeStorage(): DraftStorage {
	const map = new Map<string, string>();
	return {
		getItem: (key) => (map.has(key) ? map.get(key)! : null),
		setItem: (key, value) => {
			map.set(key, value);
		},
		removeItem: (key) => {
			map.delete(key);
		}
	};
}

describe('draft storage', () => {
	it('round-trips a saved draft', () => {
		const storage = fakeStorage();
		saveDraft('k', 'hello', storage);
		expect(loadDraft('k', storage)).toBe('hello');
	});

	it('returns null for a key that was never saved', () => {
		const storage = fakeStorage();
		expect(loadDraft('missing', storage)).toBeNull();
	});

	it('clears a saved draft', () => {
		const storage = fakeStorage();
		saveDraft('k', 'hello', storage);
		clearDraft('k', storage);
		expect(loadDraft('k', storage)).toBeNull();
	});
});
