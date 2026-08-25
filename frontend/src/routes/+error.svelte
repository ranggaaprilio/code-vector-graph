<script lang="ts">
	import { page } from '$app/state';
	import { SectionEyebrow, Button, EmptyState } from '$lib/components/ds';

	const status = $derived(page.status);
	const message = $derived(page.error?.message || 'Something went wrong.');
</script>

<SectionEyebrow title="Not Found" tint="salmon" />

<div class="wrap">
	<EmptyState title={`${status} — ${message}`}>
		<p>
			<code>{page.url.pathname}</code> doesn&rsquo;t match any view in this dashboard.
		</p>
		<div class="actions">
			<Button variant="primary" href="/apps">Applications</Button>
			<Button variant="secondary" href="/overview">System</Button>
		</div>
	</EmptyState>
</div>

<style>
	.wrap {
		padding: var(--space-xl);
		max-width: 640px;
	}

	.actions {
		display: flex;
		gap: var(--space-sm);
		margin-top: var(--space-lg);
	}
</style>
