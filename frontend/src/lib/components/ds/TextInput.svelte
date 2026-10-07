<script lang="ts">
	let {
		value = $bindable(''),
		type = 'text',
		placeholder = '',
		class: className = '',
		...rest
	}: {
		value?: string;
		type?: string;
		placeholder?: string;
		class?: string;
		[key: string]: unknown;
	} = $props();
</script>

<input {type} {placeholder} bind:value class="ds-input {className}" {...rest} />
