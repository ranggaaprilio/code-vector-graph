<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { appStore } from '$lib/stores/app.svelte';
	import { PageFrame, TopBanner, Button, Select, Toast, FooterBand } from '$lib/components/ds';
	import '$lib/styles/base.css';

	let { children } = $props();

	// init() returns a teardown so the 30s health poll stops with the layout
	// instead of recursing forever.
	onMount(() => appStore.init());

	const NAV = [
		{ id: 'apps', path: '/apps', label: 'Applications' },
		{ id: 'vectors', path: '/vectors', label: 'Vectors' },
		{ id: 'graph', path: '/graph', label: 'Graph' },
		{ id: 'chat', path: '/chat', label: 'AI Chat' },
		{ id: 'overview', path: '/overview', label: 'System' }
	];

	function isActive(path: string): boolean {
		return page.url.pathname === path || page.url.pathname.startsWith(`${path}/`);
	}

	const statuses = $derived([
		{ label: 'QDRANT', ok: appStore.statusOf(appStore.health.qdrant?.ok) },
		{ label: 'NEO4J', ok: appStore.statusOf(appStore.health.neo4j?.ok) },
		{ label: 'MCP', ok: appStore.statusOf(appStore.health.mcp_session?.ok) }
	]);

	function onAppChange(e: Event) {
		const value = (e.target as HTMLSelectElement).value;
		appStore.setScope(value, '');
		reflectAppsDrilldown();
	}

	function onRepoChange(e: Event) {
		const value = (e.target as HTMLSelectElement).value;
		appStore.setScope(appStore.app, value);
		reflectAppsDrilldown();
	}

	/** Only the Applications view encodes scope in its URL — drill in/out there. */
	function reflectAppsDrilldown() {
		if (!page.url.pathname.startsWith('/apps')) return;
		goto(appStore.app ? `/apps/${encodeURIComponent(appStore.app)}/overview` : '/apps');
	}
</script>

<a class="ds-skip-link" href="#main">Skip to content</a>

<PageFrame>
	<TopBanner {statuses} />

	<div class="body">
		<aside class="rail">
			<div class="scope">
				<label class="ds-ui-label" for="app-select">Application</label>
				<Select id="app-select" value={appStore.app} onchange={onAppChange}>
					<option value="">All applications</option>
					{#each appStore.apps as a (a.name)}
						<option value={a.name}>{a.name}</option>
					{/each}
				</Select>

				<label class="ds-ui-label repo-label" for="repo-select">Repository</label>
				<Select
					id="repo-select"
					value={appStore.repo}
					onchange={onRepoChange}
					disabled={!appStore.app}
				>
					<option value="">All repos in app</option>
					{#each appStore.repos as r (r.name)}
						<option value={r.name}>{r.name}</option>
					{/each}
				</Select>

				{#if appStore.appsLoaded && !appStore.apps.length}
					<p class="ds-caption hint">
						No applications indexed yet — run <code>cvg-ingest</code>; set
						<code>CVG_REPOS_ROOT</code> to group repos into one application.
					</p>
				{/if}
				{#if appStore.appsError}
					<p class="ds-caption error">{appStore.appsError}</p>
				{/if}
			</div>

			<nav class="nav">
				{#each NAV as item (item.id)}
					<Button
						variant={isActive(item.path) ? 'primary' : 'secondary'}
						current={isActive(item.path)}
						class="nav-btn"
						href={item.path}
					>
						{item.label}
					</Button>
				{/each}
			</nav>

			<div class="scope-readout ds-caption" title={appStore.scopeLabelText}>
				Scope: {appStore.scopeLabelText}
			</div>
		</aside>

		<main id="main" class="main">
			{@render children?.()}
		</main>
	</div>

	<FooterBand>Code Vector Graph — Knowledge Dashboard</FooterBand>
</PageFrame>

<Toast message={appStore.toast} onDismiss={() => (appStore.toast = '')} />

<style>
	.body {
		display: flex;
		flex: 1;
		min-height: 0;
	}

	.rail {
		width: 220px;
		flex-shrink: 0;
		border-right: var(--border-hairline);
		padding: var(--space-lg) var(--space-md);
		display: flex;
		flex-direction: column;
		gap: var(--space-xl);
	}

	.scope {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.repo-label {
		margin-top: var(--space-sm);
	}

	.hint,
	.error {
		margin-top: var(--space-xs);
	}

	.error {
		color: var(--color-primary);
	}

	.nav {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.nav :global(.nav-btn) {
		width: 100%;
		text-align: left;
	}

	.scope-readout {
		margin-top: auto;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	/* Flex column so views can use either `height: 100%` or `flex: 1`, and the
	   single scroll container for everything below it. */
	.main {
		flex: 1;
		min-width: 0;
		min-height: 0;
		display: flex;
		flex-direction: column;
		overflow: auto;
		overscroll-behavior-y: contain;
		scrollbar-gutter: stable;
	}

	@media (max-width: 768px) {
		.body {
			flex-direction: column;
		}
		/* The rail becomes a compact strip: it must not eat the screen before the
		   view it is navigating to. */
		.rail {
			width: auto;
			min-width: 0;
			border-right: none;
			border-bottom: var(--border-hairline);
			gap: var(--space-md);
			padding: var(--space-md);
		}
		.scope {
			flex-direction: row;
			flex-wrap: wrap;
			align-items: flex-end;
			gap: var(--space-sm);
		}
		.scope :global(.ds-input) {
			width: auto;
			min-width: 0;
			flex: 1 1 140px;
		}
		.repo-label {
			margin-top: 0;
		}
		.nav {
			flex-direction: row;
			flex-wrap: wrap;
		}
		/* width:auto matters: the desktop rule sets width:100%, and `flex-basis:
		   auto` resolves to the width property — which put every nav item on its
		   own row instead of wrapping into a strip. */
		.nav :global(.nav-btn) {
			width: auto;
			/* No grow: a lone item on the second row should stay button-sized
			   instead of stretching across it. */
			flex: 0 1 auto;
			min-width: 0;
			text-align: center;
			padding: var(--space-s) var(--space-sm);
		}
		.scope-readout {
			margin-top: 0;
		}
		/* The page scrolls at this width, not the pane. */
		.main {
			overflow: visible;
		}
	}
</style>
