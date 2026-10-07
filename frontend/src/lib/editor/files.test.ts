// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { MarkdownFileError, readMarkdownFile, suggestFilename } from './files';

describe('suggestFilename', () => {
	it('derives a filename from the title', () => {
		expect(suggestFilename('Deploy Runbook')).toBe('deploy-runbook.md');
	});

	it('falls back to "untitled.md" when there is no title', () => {
		expect(suggestFilename(null)).toBe('untitled.md');
		expect(suggestFilename('')).toBe('untitled.md');
	});
});

describe('readMarkdownFile', () => {
	it('resolves with the file contents', async () => {
		const file = new File(['# Hello'], 'note.md', { type: 'text/markdown' });
		const result = await readMarkdownFile(file);
		expect(result).toEqual({ name: 'note.md', text: '# Hello' });
	});

	it('rejects a disallowed extension', async () => {
		const file = new File(['x'], 'note.exe', { type: 'application/octet-stream' });
		await expect(readMarkdownFile(file)).rejects.toBeInstanceOf(MarkdownFileError);
	});

	it('rejects a file over the size limit', async () => {
		const file = new File(['x'.repeat(100)], 'note.md', { type: 'text/markdown' });
		await expect(readMarkdownFile(file, 10)).rejects.toBeInstanceOf(MarkdownFileError);
	});
});
