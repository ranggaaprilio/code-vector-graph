<script lang="ts">
	import { tintForLabel } from '$lib/utils/tints';

	let { label, kind = 'default' }: { label: string; kind?: 'default' | 'code' | 'wiki' } =
		$props();
</script>

<span class="badge ds-caption badge-{kind}" style="background: var(--tint-{tintForLabel(label)})">
	{label}
</span>

<style>
	.badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: var(--radius-sm);
		color: var(--color-ink);
		white-space: nowrap;
		font-weight: 600;
	}
</style>
