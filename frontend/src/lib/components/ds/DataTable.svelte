<script lang="ts">
	type Column = { key: string; label: string };

	let {
		columns,
		rows
	}: {
		columns: Column[];
		rows: Record<string, unknown>[];
	} = $props();

	function cell(row: Record<string, unknown>, key: string): string {
		const v = row[key];
		if (v == null) return '';
		return typeof v === 'string' ? v : JSON.stringify(v);
	}

	/** Figures that get compared down a column deserve tabular numerals. */
	function isNumeric(row: Record<string, unknown>, key: string): boolean {
		return typeof row[key] === 'number';
	}
</script>

<div class="ds-scroll-x">
	<table class="ds-table">
		<thead>
			<tr>
				{#each columns as col (col.key)}
					<th scope="col" class="ds-ui-label">{col.label}</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each rows as row, i (i)}
				<tr>
					{#each columns as col (col.key)}
						<td class="ds-body-sm ds-mono" class:num={isNumeric(row, col.key)}>
							{cell(row, col.key)}
						</td>
					{/each}
				</tr>
			{/each}
			{#if !rows.length}
				<tr class="empty">
					<td class="ds-body-sm" colspan={columns.length}>No rows.</td>
				</tr>
			{/if}
		</tbody>
	</table>
</div>

<style>
	.ds-table {
		width: 100%;
		border-collapse: collapse;
	}

	.ds-table th,
	.ds-table td {
		border-bottom: var(--border-hairline);
		padding: var(--space-xs) var(--space-sm);
		text-align: left;
		vertical-align: top;
		white-space: nowrap;
	}

	.ds-table th {
		background: var(--color-canvas);
		position: sticky;
		top: 0;
		/* The header must stay legible over rows scrolling beneath it. */
		box-shadow: 0 1px 0 var(--color-frame-ink);
	}

	.ds-table tbody tr:nth-child(even) {
		background: var(--color-row-zebra);
	}

	.ds-table tbody tr:not(.empty):hover {
		background: var(--color-row-hover);
	}

	.num {
		font-variant-numeric: tabular-nums;
		text-align: right;
	}
</style>
