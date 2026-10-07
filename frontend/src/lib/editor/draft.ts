/** localStorage-backed autosave for the standalone /editor page. `storage`
 * is injectable (a Map-like fake in tests) so this stays framework-free. */

export interface DraftStorage {
	getItem(key: string): string | null;
	setItem(key: string, value: string): void;
	removeItem(key: string): void;
}

function safeStorage(storage?: DraftStorage): DraftStorage | null {
	if (storage) return storage;
	try {
		return typeof localStorage !== 'undefined' ? localStorage : null;
	} catch {
		return null;
	}
}

export function loadDraft(key: string, storage?: DraftStorage): string | null {
	const s = safeStorage(storage);
	if (!s) return null;
	try {
		return s.getItem(key);
	} catch {
		return null;
	}
}

export function saveDraft(key: string, text: string, storage?: DraftStorage): void {
	const s = safeStorage(storage);
	if (!s) return;
	try {
		s.setItem(key, text);
	} catch {
		// storage full/blocked — the draft simply isn't persisted this time.
	}
}

export function clearDraft(key: string, storage?: DraftStorage): void {
	const s = safeStorage(storage);
	if (!s) return;
	try {
		s.removeItem(key);
	} catch {
		// nothing to do — already gone or storage unavailable.
	}
}
