/** Small, dependency-free text stats for the Markdown editor's footer and
 * for deriving a title/slug preview from the body — mirrors the server's
 * `extract_title`/`slugify` (ingestion/okf/features/template.py,documents.py)
 * closely enough for an instant client-side preview; the server remains the
 * source of truth for what actually gets saved. */

export function wordCount(text: string): number {
	const matches = text.match(/\S+/g);
	return matches ? matches.length : 0;
}

export function charCount(text: string): number {
	return text.length;
}

const H1_RE = /^#\s+(.+?)\s*$/;

/** The H1 title, if the body's first non-blank line is a '# ' heading. */
export function extractTitle(body: string): string | null {
	for (const line of body.split('\n')) {
		if (!line.trim()) continue;
		const m = H1_RE.exec(line);
		return m ? m[1].trim() : null;
	}
	return null;
}

/** Client-side preview of the slug the server will assign — not
 * authoritative (the server also de-duplicates against existing slugs). */
export function slugifyPreview(title: string, maxLen = 80): string {
	const base = (title || '')
		.trim()
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-+|-+$/g, '')
		.slice(0, maxLen)
		.replace(/^-+|-+$/g, '');
	return base || 'document';
}
