import { describe, expect, it } from 'vitest';
import { charCount, extractTitle, slugifyPreview, wordCount } from './stats';

describe('wordCount', () => {
	it('counts whitespace-separated tokens', () => {
		expect(wordCount('one two   three\nfour')).toBe(4);
		expect(wordCount('')).toBe(0);
	});
});

describe('charCount', () => {
	it('returns the raw character length', () => {
		expect(charCount('hello')).toBe(5);
	});
});

describe('extractTitle', () => {
	it('reads the first non-blank line as the H1 title', () => {
		expect(extractTitle('# My Title\n\nBody')).toBe('My Title');
	});

	it('returns null when the first non-blank line is not an H1', () => {
		expect(extractTitle('Just text')).toBeNull();
	});

	it('skips leading blank lines', () => {
		expect(extractTitle('\n\n# Title\nBody')).toBe('Title');
	});
});

describe('slugifyPreview', () => {
	it('lowercases and replaces punctuation', () => {
		expect(slugifyPreview('Deploy Runbook v2!')).toBe('deploy-runbook-v2');
	});

	it('falls back to "document" for empty/non-alphanumeric titles', () => {
		expect(slugifyPreview('')).toBe('document');
		expect(slugifyPreview('日本語')).toBe('document');
	});
});
