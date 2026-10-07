import { defineConfig } from 'vitest/config';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';

// Builds straight into the FastAPI package's static dir — no copy step.
// SvelteKit's own asset paths (/_app/...) are root-relative, and the FastAPI
// catch-all route (see api/app.py) serves any matching file from STATIC_DIR
// directly, falling back to index.html for client-side routes.
const STATIC_OUT = '../src/code_vector_graph/api/static';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) => filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter({
				pages: STATIC_OUT,
				assets: STATIC_OUT,
				fallback: 'index.html',
				precompress: false,
				strict: false
			})
		})
	],
	server: {
		proxy: {
			'/api': 'http://127.0.0.1:8001'
		}
	},
	test: {
		expect: { requireAssertions: true },
		projects: [
			{
				extends: './vite.config.ts',
				test: {
					name: 'server',
					environment: 'node',
					include: ['src/**/*.{test,spec}.{js,ts}'],
					exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
				}
			}
		]
	}
});
