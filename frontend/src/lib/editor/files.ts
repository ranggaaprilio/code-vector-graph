/** Client-side .md file load/save for the Markdown editor — no network
 * round-trip needed for "open a file" or "download what I wrote". */

const MAX_BYTES_DEFAULT = 2_000_000;
const ALLOWED_EXTENSIONS = ['.md', '.markdown', '.txt'];

export class MarkdownFileError extends Error {}

function hasAllowedExtension(name: string): boolean {
	const lower = name.toLowerCase();
	return ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export function readMarkdownFile(file: File, maxBytes: number = MAX_BYTES_DEFAULT): Promise<{ name: string; text: string }> {
	if (!hasAllowedExtension(file.name)) {
		return Promise.reject(new MarkdownFileError(`"${file.name}" isn't a .md/.markdown/.txt file.`));
	}
	if (file.size > maxBytes) {
		return Promise.reject(new MarkdownFileError(`"${file.name}" is too large (max ${Math.round(maxBytes / 1_000_000)}MB).`));
	}
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve({ name: file.name, text: String(reader.result ?? '') });
		reader.onerror = () => reject(new MarkdownFileError(`Could not read "${file.name}".`));
		reader.readAsText(file);
	});
}

export function suggestFilename(title: string | null | undefined): string {
	const base = (title || 'untitled')
		.trim()
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-+|-+$/g, '');
	return `${base || 'untitled'}.md`;
}

/** Trigger a browser "Save As" for `text` as a `.md` file. No-op outside a
 * browser (SSR guard — this module is only ever called client-side). */
export function downloadMarkdown(filename: string, text: string): void {
	if (typeof document === 'undefined') return;
	const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	a.remove();
	URL.revokeObjectURL(url);
}
