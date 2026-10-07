/** Pure text-manipulation helpers behind the Markdown editor's toolbar and
 * keyboard shortcuts. Every function takes the full text + a selection
 * range and returns the new text + where the selection should land after —
 * the caller (MarkdownEditor.svelte) applies it to the actual <textarea>. */

export type Sel = { start: number; end: number };
export type Edit = { text: string; selection: Sel };

export type ToolbarAction =
	| 'bold'
	| 'italic'
	| 'strike'
	| 'code'
	| 'h1'
	| 'h2'
	| 'h3'
	| 'quote'
	| 'ul'
	| 'ol'
	| 'link'
	| 'codeblock'
	| 'table'
	| 'mermaid'
	| 'hr';

export const MERMAID_SNIPPET = '```mermaid\nflowchart TD\n\tA[Start] --> B[End]\n```\n';

export function codeBlock(lang = ''): string {
	return `\`\`\`${lang}\ncode\n\`\`\`\n`;
}

/** Wrap the selection in `before`/`after` (default: same string both sides),
 * toggling it off if the selection is already wrapped. An empty selection
 * gets `placeholder` as the wrapped text, pre-selected for overtyping. */
export function wrapSelection(text: string, sel: Sel, before: string, after: string = before, placeholder = 'text'): Edit {
	const { start, end } = sel;
	const selected = text.slice(start, end);

	const beforeStart = start - before.length;
	const afterEnd = end + after.length;
	const alreadyWrapped =
		beforeStart >= 0 &&
		afterEnd <= text.length &&
		text.slice(beforeStart, start) === before &&
		text.slice(end, afterEnd) === after;

	if (alreadyWrapped) {
		const newText = text.slice(0, beforeStart) + selected + text.slice(afterEnd);
		return { text: newText, selection: { start: beforeStart, end: beforeStart + selected.length } };
	}

	const inner = selected || placeholder;
	const newText = text.slice(0, start) + before + inner + after + text.slice(end);
	const innerStart = start + before.length;
	return { text: newText, selection: { start: innerStart, end: innerStart + inner.length } };
}

function lineBounds(text: string, pos: number): { start: number; end: number } {
	const start = text.lastIndexOf('\n', Math.max(0, pos - 1)) + 1;
	const nextBreak = text.indexOf('\n', pos);
	const end = nextBreak === -1 ? text.length : nextBreak;
	return { start, end };
}

function linesInRange(text: string, sel: Sel): { start: number; end: number } {
	const first = lineBounds(text, sel.start).start;
	const last = sel.end > sel.start ? lineBounds(text, sel.end - 1).end : lineBounds(text, sel.start).end;
	return { start: first, end: last };
}

export function isListLine(line: string): boolean {
	return /^\s*([-*+]|\d+\.)\s/.test(line);
}

const HEADING_RE = /^(#{1,6})\s+/;

/** Toggle a per-line prefix (heading level, blockquote, bullet/numbered
 * list) across every line touched by the selection. `prefix` may be a
 * fixed string or a function of the 0-based line index (for numbered
 * lists, so re-numbering starts at 1 each time). */
export function toggleLinePrefix(text: string, sel: Sel, prefix: string | ((i: number) => string)): Edit {
	const range = linesInRange(text, sel);
	const block = text.slice(range.start, range.end);
	const lines = block.length ? block.split('\n') : [''];

	const prefixFor = (i: number) => (typeof prefix === 'function' ? prefix(i) : prefix);
	const isHeadingToggle = typeof prefix === 'string' && HEADING_RE.test(prefix + 'x');

	const alreadyApplied = lines.every((line, i) => {
		const p = prefixFor(i);
		if (isHeadingToggle) return HEADING_RE.test(line) && line.startsWith(p);
		return line.startsWith(p);
	});

	const newLines = lines.map((line, i) => {
		const p = prefixFor(i);
		if (alreadyApplied) {
			return line.startsWith(p) ? line.slice(p.length) : line;
		}
		if (isHeadingToggle && HEADING_RE.test(line)) {
			return p + line.replace(HEADING_RE, '');
		}
		return p + line;
	});

	const newBlock = newLines.join('\n');
	const newText = text.slice(0, range.start) + newBlock + text.slice(range.end);
	const delta = newBlock.length - block.length;
	return { text: newText, selection: { start: range.start, end: range.end + delta } };
}

/** Insert a block, guaranteeing a blank line before and after it. */
export function insertBlock(text: string, sel: Sel, block: string): Edit {
	const before = text.slice(0, sel.start);
	const after = text.slice(sel.end);
	const needsLeadingBreak = before.length > 0 && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : '';
	const needsTrailingBreak = after.length > 0 && !after.startsWith('\n\n') ? (after.startsWith('\n') ? '\n' : '\n\n') : '';
	const insert = needsLeadingBreak + block + needsTrailingBreak;
	const newText = before + insert + after;
	const insertStart = before.length + needsLeadingBreak.length;
	return { text: newText, selection: { start: insertStart, end: insertStart + block.length } };
}

export function insertLink(text: string, sel: Sel, url = 'https://'): Edit {
	const selected = text.slice(sel.start, sel.end) || 'link text';
	const markdown = `[${selected}](${url})`;
	const newText = text.slice(0, sel.start) + markdown + text.slice(sel.end);
	const urlStart = sel.start + selected.length + 3; // "[selected](".length - 1 char slack handled below
	const linkTextStart = sel.start + 1;
	return sel.start === sel.end
		? { text: newText, selection: { start: linkTextStart, end: linkTextStart + selected.length } }
		: { text: newText, selection: { start: urlStart, end: urlStart + url.length } };
}

export function tableSnippet(cols = 3, rows = 2): string {
	const header = `| ${Array.from({ length: cols }, (_, i) => `Col ${i + 1}`).join(' | ')} |`;
	const divider = `| ${Array.from({ length: cols }, () => '---').join(' | ')} |`;
	const row = `| ${Array.from({ length: cols }, () => ' ').join(' | ')} |`;
	return [header, divider, ...Array.from({ length: rows }, () => row)].join('\n') + '\n';
}

/** Indent (dir=1) or outdent (dir=-1) every line touched by the selection,
 * but only lines that look like a list item, or when the selection already
 * spans more than one line (so Tab in a single non-list line still just
 * moves focus, handled by the caller). */
export function indentLines(text: string, sel: Sel, dir: 1 | -1, unit = '  '): Edit {
	const range = linesInRange(text, sel);
	const block = text.slice(range.start, range.end);
	const lines = block.split('\n');
	const multiLine = lines.length > 1;

	const newLines = lines.map((line) => {
		if (!multiLine && !isListLine(line)) return line;
		if (dir === 1) return unit + line;
		if (line.startsWith(unit)) return line.slice(unit.length);
		return line.replace(/^\s{1,2}/, '');
	});

	const newBlock = newLines.join('\n');
	const newText = text.slice(0, range.start) + newBlock + text.slice(range.end);
	const delta = newBlock.length - block.length;
	return { text: newText, selection: { start: range.start, end: range.end + delta } };
}

export function applyFormat(text: string, sel: Sel, action: ToolbarAction): Edit {
	switch (action) {
		case 'bold':
			return wrapSelection(text, sel, '**');
		case 'italic':
			return wrapSelection(text, sel, '_');
		case 'strike':
			return wrapSelection(text, sel, '~~');
		case 'code':
			return wrapSelection(text, sel, '`');
		case 'h1':
			return toggleLinePrefix(text, sel, '# ');
		case 'h2':
			return toggleLinePrefix(text, sel, '## ');
		case 'h3':
			return toggleLinePrefix(text, sel, '### ');
		case 'quote':
			return toggleLinePrefix(text, sel, '> ');
		case 'ul':
			return toggleLinePrefix(text, sel, '- ');
		case 'ol':
			return toggleLinePrefix(text, sel, (i) => `${i + 1}. `);
		case 'link':
			return insertLink(text, sel);
		case 'codeblock':
			return insertBlock(text, sel, codeBlock());
		case 'table':
			return insertBlock(text, sel, tableSnippet());
		case 'mermaid':
			return insertBlock(text, sel, MERMAID_SNIPPET);
		case 'hr':
			return insertBlock(text, sel, '---');
		default:
			return { text, selection: sel };
	}
}
