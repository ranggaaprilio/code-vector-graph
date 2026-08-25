<script lang="ts">
	type Item = { value: string; label: string; href?: string; title?: string };

	let {
		items,
		active,
		onSelect,
		ariaLabel,
		class: className = ''
	}: {
		items: Item[];
		active: string;
		/** Only used for the button flavour (in-page filters). */
		onSelect?: (value: string) => void;
		ariaLabel: string;
		class?: string;
	} = $props();

	// Route tabs are links (so they deep-link and open in a new tab); in-page
	// filters are buttons. role="tablist" is deliberately avoided: it promises a
	// tabpanel relationship that neither flavour actually has.
	const asLinks = $derived(items.some((i) => i.href));

	/** Arrow keys walk a segmented control, the way a native one does. */
	function onKeydown(e: KeyboardEvent) {
		const delta = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
		if (!delta) return;
		const self = e.currentTarget as HTMLElement;
		const siblings = Array.from(self.parentElement?.children ?? []) as HTMLElement[];
		const tabs = siblings.filter((el) => el.classList.contains('tab'));
		const i = tabs.indexOf(self);
		if (i < 0) return;
		e.preventDefault();
		tabs[(i + delta + tabs.length) % tabs.length].focus();
	}
</script>

{#if asLinks}
	<nav class="tabs {className}" aria-label={ariaLabel}>
		{#each items as it (it.value)}
			<a
				href={it.href}
				title={it.title}
				class="tab ds-ui-label"
				class:active={it.value === active}
				aria-current={it.value === active ? 'page' : undefined}
				onkeydown={onKeydown}
			>
				{it.label}
			</a>
		{/each}
	</nav>
{:else}
	<div class="tabs {className}" role="group" aria-label={ariaLabel}>
		{#each items as it (it.value)}
			<button
				type="button"
				title={it.title}
				class="tab ds-ui-label"
				class:active={it.value === active}
				aria-pressed={it.value === active}
				onclick={() => onSelect?.(it.value)}
				onkeydown={onKeydown}
			>
				{it.label}
			</button>
		{/each}
	</div>
{/if}

<style>
	.tabs {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-s);
	}

	.tab {
		background: var(--color-canvas);
		color: var(--color-ink);
		border: var(--border-hairline);
		border-radius: var(--radius-none);
		padding: var(--space-s) var(--space-md);
		text-decoration: none;
		cursor: pointer;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		transition:
			background-color var(--motion-fast) var(--ease-snap),
			color var(--motion-fast) var(--ease-snap),
			translate var(--motion-fast) var(--ease-snap);
	}

	.tab:hover:not(.active) {
		background: var(--color-row-hover);
	}

	.tab:active {
		translate: 1px 1px;
	}

	/* Selected segment inverts, matching button-primary. */
	.tab.active {
		background: var(--color-frame-ink);
		color: var(--color-canvas);
		cursor: default;
	}
</style>
