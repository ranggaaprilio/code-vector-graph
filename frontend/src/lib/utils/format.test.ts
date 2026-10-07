// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import {
	basename,
	dirname,
	breadcrumbs,
	relToRoot,
	repoOf,
	hljsLang,
	isWiki,
	locationStr,
	topEntries,
	renderMarkdown,
	escapeHtml,
	scopeLabel,
	findRepo,
	explorerTarget,
	langEntries,
	type AppInfo
} from './format';

describe('format', () => {
	it('basename / dirname', () => {
		expect(basename('/a/b/c.ts')).toBe('c.ts');
		expect(basename('c.ts')).toBe('c.ts');
		expect(basename('/a/b/')).toBe('b');
		expect(dirname('/a/b/c.ts')).toBe('/a/b');
		expect(dirname('a/b/c.ts')).toBe('a/b');
		expect(dirname('c.ts')).toBe('');
		expect(dirname('/c.ts')).toBe('/');
	});

	it('breadcrumbs builds cumulative paths', () => {
		expect(breadcrumbs('src/lib/x.js')).toEqual([
			{ name: 'src', path: 'src' },
			{ name: 'lib', path: 'src/lib' },
			{ name: 'x.js', path: 'src/lib/x.js' }
		]);
		expect(breadcrumbs('/a/b')).toEqual([
			{ name: 'a', path: '/a' },
			{ name: 'b', path: '/a/b' }
		]);
		expect(breadcrumbs('')).toEqual([]);
	});

	it('relToRoot strips a matching root only', () => {
		expect(relToRoot('/r/onebid/tnlm/src/a.ts', '/r/onebid/tnlm')).toBe('src/a.ts');
		expect(relToRoot('/r/onebid/tnlm/src/a.ts', '/r/onebid/tnlm/')).toBe('src/a.ts');
		expect(relToRoot('/r/onebid/tnlm-extra/src/a.ts', '/r/onebid/tnlm')).toBe(
			'/r/onebid/tnlm-extra/src/a.ts'
		);
		expect(relToRoot('/r/x/a.ts', '')).toBe('/r/x/a.ts');
		expect(relToRoot('/r/x', '/r/x')).toBe('');
	});

	it('repoOf: explicit wins, then longest root prefix, else null', () => {
		const repos = [
			{ name: 'outer', root: '/r/onebid' },
			{ name: 'tnlm', root: '/r/onebid/backend/backend_nodejs_global_tnlm' },
			{ name: 'sync', root: '/r/onebid/backend/backend_nodejs_data_sync_onebid/' }
		];
		expect(repoOf('/anything', repos, 'recorded')).toBe('recorded');
		expect(repoOf('/r/onebid/backend/backend_nodejs_global_tnlm/src/a.ts', repos)).toBe('tnlm');
		expect(repoOf('/r/onebid/backend/backend_nodejs_data_sync_onebid/index.js', repos)).toBe(
			'sync'
		);
		expect(repoOf('/r/onebid/backend/other/x.ts', repos)).toBe('outer');
		expect(repoOf('/elsewhere/x.ts', repos)).toBe(null);
		expect(repoOf('', repos)).toBe(null);
		expect(repoOf('/r/onebid/x.ts', [])).toBe(null);
	});

	it('hljsLang maps indexed languages to highlight.js ids', () => {
		expect(hljsLang('typescript')).toBe('typescript');
		expect(hljsLang('tsx')).toBe('typescript');
		expect(hljsLang('javascript')).toBe('javascript');
		expect(hljsLang('jsx')).toBe('javascript');
		expect(hljsLang('python')).toBe('python');
		expect(hljsLang('brainfuck')).toBe('plaintext');
		expect(hljsLang(undefined)).toBe('plaintext');
		expect(hljsLang('typescript', true)).toBe('markdown');
	});

	it('isWiki detects wiki payloads', () => {
		expect(isWiki({ source: 'wiki' })).toBe(true);
		expect(isWiki({ source: 'okf_wiki' })).toBe(true);
		expect(isWiki({ concept_id: 'abc' })).toBe(true);
		expect(isWiki({ source: 'code' })).toBe(false);
		expect(isWiki({})).toBe(false);
		expect(isWiki(null)).toBe(false);
	});

	it('locationStr', () => {
		expect(locationStr({})).toBe('unknown');
		expect(locationStr({ file_path: '/a/b/c.ts' })).toBe('b/c.ts');
		expect(locationStr({ file_path: '/a/b/c.ts', start_line: 5, end_line: 9 })).toBe('b/c.ts:5-9');
		expect(locationStr({ file_path: '/a/b/c.ts', start_line: 5 })).toBe('b/c.ts:5');
		expect(locationStr({ file_path: '/a/b/c.ts', start_line: 5, end_line: 5 })).toBe('b/c.ts:5');
	});

	it('topEntries sorts descending and limits', () => {
		const counts = { File: 3, Function: 10, Class: 7 };
		expect(topEntries(counts, 2)).toEqual([
			['Function', 10],
			['Class', 7]
		]);
		expect(topEntries(counts)).toEqual([
			['Function', 10],
			['Class', 7],
			['File', 3]
		]);
		expect(topEntries(null)).toEqual([]);
	});

	it('renderMarkdown renders and sanitises', () => {
		expect(renderMarkdown('')).toBe('');
		expect(renderMarkdown(null)).toBe('');
		expect(renderMarkdown('**hi**')).toContain('<strong>hi</strong>');
		expect(renderMarkdown('<script>bad()</script>hi')).not.toContain('<script>');
	});

	it('escapeHtml escapes the standard set', () => {
		expect(escapeHtml('<script>x</script> & "q"')).toBe(
			'&lt;script&gt;x&lt;/script&gt; &amp; &quot;q&quot;'
		);
	});

	it('scopeLabel', () => {
		expect(scopeLabel('', '')).toBe('All applications');
		expect(scopeLabel('onebid', '')).toBe('onebid · all repos');
		expect(scopeLabel('onebid', 'backend_nodejs_global_tnlm')).toBe(
			'onebid · backend_nodejs_global_tnlm'
		);
	});

	const APPS: AppInfo[] = [
		{
			name: 'onebid',
			repos: [
				{ name: 'tnlm', root: '/r/onebid/backend/backend_nodejs_global_tnlm' },
				{ name: 'sync', root: '/r/onebid/backend/backend_nodejs_data_sync_onebid' }
			]
		},
		{ name: 'other', repos: [{ name: 'solo', root: '/r/other' }] }
	];

	it('findRepo locates a repo across apps', () => {
		expect(findRepo(APPS, 'sync')?.app.name).toBe('onebid');
		expect(findRepo(APPS, 'solo')?.repo.root).toBe('/r/other');
		expect(findRepo(APPS, 'nope')).toBe(null);
		expect(findRepo([], 'sync')).toBe(null);
		expect(findRepo(APPS, '')).toBe(null);
	});

	it('explorerTarget resolves repo from payload or path prefix', () => {
		expect(
			explorerTarget(APPS, {
				file_path: '/r/onebid/backend/backend_nodejs_global_tnlm/src/a.ts'
			})
		).toEqual({ app: 'onebid', repo: 'tnlm', path: 'src/a.ts' });
		expect(
			explorerTarget(APPS, { file_path: '/whatever/a.ts', repo: 'solo', rel_path: 'x/a.ts' })
		).toEqual({ app: 'other', repo: 'solo', path: 'x/a.ts' });
		expect(explorerTarget(APPS, { file_path: '/elsewhere/a.ts' })).toBe(null);
		expect(
			explorerTarget(APPS, { file_path: 'src/a.ts', repo: 'ghost' }, 'onebid')
		).toEqual({ app: 'onebid', repo: 'ghost', path: 'src/a.ts' });
		expect(explorerTarget(APPS, { file_path: 'src/a.ts', repo: 'ghost' })).toBe(null);
		expect(explorerTarget(APPS, null)).toBe(null);
	});

	it('langEntries normalises object / array shapes', () => {
		expect(langEntries({ typescript: 5, javascript: 9 })).toEqual([
			['javascript', 9],
			['typescript', 5]
		]);
		expect(langEntries(['typescript', 'javascript'])).toEqual([
			['typescript', 0],
			['javascript', 0]
		]);
		expect(
			langEntries([
				{ name: 'ts', count: 1 },
				{ language: 'js', files: 4 }
			])
		).toEqual([
			['js', 4],
			['ts', 1]
		]);
		expect(langEntries(null)).toEqual([]);
		expect(langEntries('typescript')).toEqual([]);
	});
});
