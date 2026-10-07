<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { Button, Tabs } from '$lib/components/ds';
	import { appStore } from '$lib/stores/app.svelte';

	let { data, children } = $props();

	const repos = $derived((data.appDetail as { repos?: { name: string }[] } | null)?.repos ?? []);

	const TABS = [
		{ value: 'overview', label: 'Overview' },
		{ value: 'files', label: 'Files' },
		{ value: 'docs', label: 'Docs' },
		{ value: 'wiki', label: 'Wiki' }
	];

	function tabPath(id: string): string {
		return `/apps/${encodeURIComponent(data.appName)}/${id}`;
	}

	const routeTabs = $derived(TABS.map((t) => ({ ...t, href: tabPath(t.value) })));

	const activeTab = $derived(
		TABS.find((t) => page.url.pathname.startsWith(tabPath(t.value)))?.value ?? 'overview'
	);

	// A deep link like /apps/x/files?repo=y must show y as selected even when the
	// store was never told about it, so the URL wins where it says anything.
	const activeRepo = $derived(page.url.searchParams.get('repo') || appStore.repo);

	// ...and the store follows, so /vectors, /graph and /chat inherit the scope.
	$effect(() => {
		const fromUrl = page.url.searchParams.get('repo') || '';
		if (fromUrl && fromUrl !== appStore.repo) {
			appStore.setScope(data.appName, fromUrl);
		}
	});

	// "All repos" plus one segment per repo. These were inert <span>s after the
	// SvelteKit port, which lost the old per-repo narrowing entirely.
	const repoTabs = $derived([
		{ value: '', label: 'All repos' },
		...repos.map((r) => ({ value: r.name, label: r.name, title: r.name }))
	]);

	/** Narrow the whole app view to one repo: store scope + this tab's ?repo=. */
	function selectRepo(repo: string) {
		appStore.setScope(data.appName, repo);
		const q = new URLSearchParams(page.url.searchParams);
		if (repo) q.set('repo', repo);
		else q.delete('repo');
		// These all address a location inside the previous repo.
		for (const k of ['path', 'file', 'concept', 'offset']) q.delete(k);
		const qs = q.toString();
		goto(`${page.url.pathname}${qs ? `?${qs}` : ''}`, { keepFocus: true, noScroll: true });
	}
</script>

<div class="app-detail">
	<div class="header">
		<Button variant="secondary" href="/apps">&larr; Back</Button>
		<h1 class="ds-h1">{data.appName}</h1>
	</div>

	{#if data.appError}
		<p class="ds-body-sm error">{data.appError}</p>
	{:else if repos.length}
		<div class="repo-strip">
			<Tabs
				items={repoTabs}
				active={activeRepo}
				onSelect={selectRepo}
				ariaLabel="Repository scope"
			/>
		</div>
	{/if}

	<div class="tab-strip">
		<Tabs items={routeTabs} active={activeTab} ariaLabel="Application sections" />
	</div>

	<div class="tab-content">
		{@render children?.()}
	</div>
</div>

<style>
	.app-detail {
		display: flex;
		flex-direction: column;
		min-height: 100%;
	}

	.header {
		display: flex;
		align-items: center;
		gap: var(--space-lg);
		padding: var(--space-lg);
		border-bottom: var(--border-hairline);
	}

	.error {
		color: var(--color-danger);
		padding: 0 var(--space-lg);
	}

	.repo-strip,
	.tab-strip {
		padding: var(--space-sm) var(--space-lg);
		border-bottom: var(--border-hairline);
	}

	.tab-content {
		flex: 1;
		min-height: 0;
	}
</style>
