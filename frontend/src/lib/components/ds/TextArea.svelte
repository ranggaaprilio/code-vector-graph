<script lang="ts">
	let {
		value = $bindable(''),
		el = $bindable(undefined),
		placeholder = '',
		rows = 3,
		class: className = '',
		...rest
	}: {
		value?: string;
		el?: HTMLTextAreaElement;
		placeholder?: string;
		rows?: number;
		class?: string;
		[key: string]: unknown;
	} = $props();
</script>

<textarea
	{placeholder}
	{rows}
	bind:value
	bind:this={el}
	class="ds-input ds-textarea {className}"
	{...rest}
></textarea>

<style>
	.ds-textarea {
		resize: vertical;
	}
</style>
