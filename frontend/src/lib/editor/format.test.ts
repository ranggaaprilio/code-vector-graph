import { describe, expect, it } from 'vitest';
import {
	applyFormat,
	indentLines,
	insertBlock,
	insertLink,
	isListLine,
	tableSnippet,
	toggleLinePrefix,
	wrapSelection
} from './format';

describe('wrapSelection', () => {
	it('wraps a selection and re-selects the inner text', () => {
		const result = wrapSelection('hello world', { start: 0, end: 5 }, '**');
		expect(result.text).toBe('**hello** world');
		expect(result.selection).toEqual({ start: 2, end: 7 });
	});

	it('toggles the wrap off when already wrapped', () => {
		const result = wrapSelection('**hello** world', { start: 2, end: 7 }, '**');
		expect(result.text).toBe('hello world');
		expect(result.selection).toEqual({ start: 0, end: 5 });
	});

	it('inserts a placeholder for an empty selection', () => {
		const result = wrapSelection('hello ', { start: 6, end: 6 }, '**', '**', 'bold');
		expect(result.text).toBe('hello **bold**');
		expect(result.selection).toEqual({ start: 8, end: 12 });
	});
});

describe('toggleLinePrefix (headings)', () => {
	it('adds a heading prefix', () => {
		const result = toggleLinePrefix('Title', { start: 0, end: 5 }, '# ');
		expect(result.text).toBe('# Title');
	});

	it('toggles the same heading level off', () => {
		const result = toggleLinePrefix('# Title', { start: 2, end: 7 }, '# ');
		expect(result.text).toBe('Title');
	});

	it('replaces a different heading level instead of toggling off', () => {
		const result = toggleLinePrefix('## Title', { start: 3, end: 8 }, '# ');
		expect(result.text).toBe('# Title');
	});
});

describe('toggleLinePrefix (lists)', () => {
	it('applies a bullet to every selected line', () => {
		const text = 'one\ntwo\nthree';
		const result = toggleLinePrefix(text, { start: 0, end: text.length }, '- ');
		expect(result.text).toBe('- one\n- two\n- three');
	});

	it('numbers lines starting at 1 via a prefix function', () => {
		const text = 'one\ntwo\nthree';
		const result = toggleLinePrefix(text, { start: 0, end: text.length }, (i) => `${i + 1}. `);
		expect(result.text).toBe('1. one\n2. two\n3. three');
	});

	it('removes an existing bullet on toggle', () => {
		const text = '- one\n- two';
		const result = toggleLinePrefix(text, { start: 0, end: text.length }, '- ');
		expect(result.text).toBe('one\ntwo');
	});
});

describe('insertBlock', () => {
	it('surrounds the inserted block with blank lines', () => {
		const result = insertBlock('before', { start: 6, end: 6 }, '```\ncode\n```');
		expect(result.text).toBe('before\n\n```\ncode\n```');
	});

	it('does not add extra blank lines at the very start of the document', () => {
		const result = insertBlock('', { start: 0, end: 0 }, '```\ncode\n```');
		expect(result.text).toBe('```\ncode\n```');
	});
});

describe('insertLink', () => {
	it('selects the url placeholder when text was selected', () => {
		const result = insertLink('See docs', { start: 4, end: 8 });
		expect(result.text).toBe('See [docs](https://)');
		expect(result.text.slice(result.selection.start, result.selection.end)).toBe('https://');
	});

	it('selects the placeholder link text when nothing was selected', () => {
		const result = insertLink('See ', { start: 4, end: 4 });
		expect(result.text).toBe('See [link text](https://)');
		expect(result.text.slice(result.selection.start, result.selection.end)).toBe('link text');
	});
});

describe('tableSnippet', () => {
	it('builds a table with the requested shape', () => {
		const snippet = tableSnippet(2, 1);
		const lines = snippet.trim().split('\n');
		expect(lines).toHaveLength(3); // header + divider + 1 row
		expect(lines[0]).toBe('| Col 1 | Col 2 |');
	});
});

describe('isListLine', () => {
	it('recognizes bullet and numbered list lines', () => {
		expect(isListLine('- item')).toBe(true);
		expect(isListLine('  * item')).toBe(true);
		expect(isListLine('1. item')).toBe(true);
		expect(isListLine('plain text')).toBe(false);
	});
});

describe('indentLines', () => {
	it('indents every line of a multi-line selection', () => {
		const text = 'a\nb\nc';
		const result = indentLines(text, { start: 0, end: text.length }, 1);
		expect(result.text).toBe('  a\n  b\n  c');
	});

	it('outdents a previously indented block', () => {
		const text = '  a\n  b';
		const result = indentLines(text, { start: 0, end: text.length }, -1);
		expect(result.text).toBe('a\nb');
	});

	it('indents a single list line but leaves a single plain line alone', () => {
		const listResult = indentLines('- item', { start: 2, end: 2 }, 1);
		expect(listResult.text).toBe('  - item');

		const plainResult = indentLines('plain', { start: 2, end: 2 }, 1);
		expect(plainResult.text).toBe('plain');
	});
});

describe('applyFormat dispatcher', () => {
	it('routes to the matching helper for every action', () => {
		expect(applyFormat('x', { start: 0, end: 1 }, 'bold').text).toBe('**x**');
		expect(applyFormat('x', { start: 0, end: 1 }, 'italic').text).toBe('_x_');
		expect(applyFormat('', { start: 0, end: 0 }, 'hr').text).toBe('---');
		expect(applyFormat('', { start: 0, end: 0 }, 'table').text).toContain('Col 1');
		expect(applyFormat('', { start: 0, end: 0 }, 'mermaid').text).toContain('```mermaid');
		expect(applyFormat('', { start: 0, end: 0 }, 'codeblock').text).toContain('```');
	});
});
