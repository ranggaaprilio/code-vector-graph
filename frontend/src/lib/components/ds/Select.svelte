<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		value = $bindable(''),
		children,
		class: className = '',
		...rest
	}: {
		value?: string;
		children?: Snippet;
		class?: string;
		[key: string]: unknown;
	} = $props();
</script>

<select bind:value class="ds-input {className}" {...rest}>
	{@render children?.()}
</select>
