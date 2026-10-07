<script lang="ts">
	import { tick } from 'svelte';
	import { TextArea, Tabs } from '$lib/components/ds';
	import { renderMarkdown, highlightWithin, renderMermaidWithin } from '$lib/utils/format';
	import { applyFormat, indentLines, isListLine, type ToolbarAction } from '$lib/editor/format';
	import { wordCount, charCount } from '$lib/editor/stats';
	import { readMarkdownFile, MarkdownFileError } from '$lib/editor/files';
	import { appStore } from '$lib/stores/app.svelte';

	let {
		value = $bindable(''),
		placeholder = '',
		minHeight = '420px',
		mode = $bindable<'split' | 'edit' | 'preview'>('split'),
		disabled = false,
		onFileLoaded,
		class: className = ''
	}: {
		value?: string;
		placeholder?: string;
		minHeight?: string;
		mode?: 'split' | 'edit' | 'preview';
		disabled?: boolean;
		onFileLoaded?: (name: string) => void;
		class?: string;
	} = $props();

	const MODE_ITEMS = [
		{ value: 'edit', label: 'Edit' },
		{ value: 'split', label: 'Split' },
		{ value: 'preview', label: 'Preview' }
	];

	let textareaEl = $state<HTMLTextAreaElement | undefined>(undefined);
	let fileInputEl = $state<HTMLInputElement | undefined>(undefined);
	let previewEl = $state<HTMLDivElement | undefined>(undefined);
	let dragging = $state(false);
	let previewTimer: ReturnType<typeof setTimeout> | undefined;

	const html = $derived(renderMarkdown(value));

	// Debounced: re-rendering (and especially mermaid diagram layout) on
	// every keystroke is not cheap enough to run per-character.
	$effect(() => {
		void html;
		if (mode === 'edit' || !previewEl) return;
		const el = previewEl;
		clearTimeout(previewTimer);
		previewTimer = setTimeout(() => {
			tick().then(() => {
				highlightWithin(el);
				renderMermaidWithin(el);
			});
		}, 400);
		return () => clearTimeout(previewTimer);
	});

	async function run(action: ToolbarAction) {
		if (!textareaEl) return;
		const sel = { start: textareaEl.selectionStart, end: textareaEl.selectionEnd };
		const result = applyFormat(value, sel, action);
		value = result.text;
		await tick();
		textareaEl.focus();
		textareaEl.setSelectionRange(result.selection.start, result.selection.end);
	}

	function currentLine(text: string, pos: number): string {
		const start = text.lastIndexOf('\n', Math.max(0, pos - 1)) + 1;
		const nextBreak = text.indexOf('\n', pos);
		const end = nextBreak === -1 ? text.length : nextBreak;
		return text.slice(start, end);
	}

	async function onKeydown(e: KeyboardEvent) {
		const mod = e.metaKey || e.ctrlKey;
		if (mod && e.key.toLowerCase() === 'b') {
			e.preventDefault();
			await run('bold');
		} else if (mod && e.key.toLowerCase() === 'i') {
			e.preventDefault();
			await run('italic');
		} else if (mod && e.key.toLowerCase() === 'k') {
			e.preventDefault();
			await run('link');
		} else if (e.key === 'Tab' && textareaEl) {
			const sel = { start: textareaEl.selectionStart, end: textareaEl.selectionEnd };
			const multiLine = value.slice(sel.start, sel.end).includes('\n');
			if (multiLine || isListLine(currentLine(value, sel.start))) {
				e.preventDefault();
				const result = indentLines(value, sel, e.shiftKey ? -1 : 1);
				value = result.text;
				await tick();
				textareaEl.focus();
				textareaEl.setSelectionRange(result.selection.start, result.selection.end);
			}
		}
	}

	async function loadFile(file: File) {
		try {
			const { name, text } = await readMarkdownFile(file);
			value = text;
			onFileLoaded?.(name);
		} catch (e) {
			appStore.showToast(e instanceof MarkdownFileError ? e.message : 'Could not read that file.');
		}
	}

	function onFileInputChange(e: Event) {
		const file = (e.currentTarget as HTMLInputElement).files?.[0];
		if (file) void loadFile(file);
		(e.currentTarget as HTMLInputElement).value = '';
	}

	function onDrop(e: DragEvent) {
		e.preventDefault();
		dragging = false;
		const file = e.dataTransfer?.files?.[0];
		if (file) void loadFile(file);
	}
</script>

<div
	class="md-editor {className}"
	class:dragging
	ondragover={(e) => {
		e.preventDefault();
		dragging = true;
	}}
	ondragleave={() => (dragging = false)}
	ondrop={onDrop}
	role="group"
	aria-label="Markdown editor"
>
	<div class="toolbar" role="toolbar" aria-label="Formatting">
		<div class="tb-group">
			<button type="button" class="tb-btn" title="Bold (Ctrl/Cmd+B)" onclick={() => run('bold')} {disabled}><strong>B</strong></button>
			<button type="button" class="tb-btn" title="Italic (Ctrl/Cmd+I)" onclick={() => run('italic')} {disabled}><em>I</em></button>
			<button type="button" class="tb-btn" title="Strikethrough" onclick={() => run('strike')} {disabled}><s>S</s></button>
			<button type="button" class="tb-btn" title="Inline code" onclick={() => run('code')} {disabled}>{'</>'}</button>
		</div>
		<div class="tb-sep"></div>
		<div class="tb-group">
			<button type="button" class="tb-btn" title="Heading 1" onclick={() => run('h1')} {disabled}>H1</button>
			<button type="button" class="tb-btn" title="Heading 2" onclick={() => run('h2')} {disabled}>H2</button>
			<button type="button" class="tb-btn" title="Heading 3" onclick={() => run('h3')} {disabled}>H3</button>
			<button type="button" class="tb-btn" title="Quote" onclick={() => run('quote')} {disabled}>&ldquo;</button>
		</div>
		<div class="tb-sep"></div>
		<div class="tb-group">
			<button type="button" class="tb-btn" title="Bullet list" onclick={() => run('ul')} {disabled}>&bull; List</button>
			<button type="button" class="tb-btn" title="Numbered list" onclick={() => run('ol')} {disabled}>1. List</button>
			<button type="button" class="tb-btn" title="Link (Ctrl/Cmd+K)" onclick={() => run('link')} {disabled}>Link</button>
			<button type="button" class="tb-btn" title="Code block" onclick={() => run('codeblock')} {disabled}>{'{ }'}</button>
			<button type="button" class="tb-btn" title="Table" onclick={() => run('table')} {disabled}>Table</button>
			<button type="button" class="tb-btn" title="Mermaid diagram" onclick={() => run('mermaid')} {disabled}>Diagram</button>
			<button type="button" class="tb-btn" title="Horizontal rule" onclick={() => run('hr')} {disabled}>&mdash;</button>
		</div>
		<div class="tb-spacer"></div>
		<button type="button" class="tb-btn" title="Open a .md file" onclick={() => fileInputEl?.click()} {disabled}>
			Open .md
		</button>
		<input
			bind:this={fileInputEl}
			type="file"
			accept=".md,.markdown,.txt"
			hidden
			onchange={onFileInputChange}
		/>
		<Tabs items={MODE_ITEMS} active={mode} onSelect={(v) => (mode = v as typeof mode)} ariaLabel="Editor view" />
	</div>

	<div class="body" class:split={mode === 'split'}>
		{#if mode !== 'preview'}
			<TextArea
				bind:value
				bind:el={textareaEl}
				{placeholder}
				{disabled}
				class="md-editor-textarea"
				style="min-height: {minHeight}"
				onkeydown={onKeydown}
			/>
		{/if}
		{#if mode !== 'edit'}
			<div class="prose ds-prose md-editor-preview" style="min-height: {minHeight}" bind:this={previewEl}>
				{@html html}
			</div>
		{/if}
	</div>

	{#if dragging}
		<div class="drop-hint ds-body-sm">Drop a .md file to load it</div>
	{/if}

	<div class="footer ds-caption">
		{wordCount(value)} words &middot; {charCount(value)} chars
	</div>
</div>

<style>
	.md-editor {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		position: relative;
		border-radius: var(--radius-md);
	}

	.md-editor.dragging {
		outline: 2px dashed var(--color-primary);
		outline-offset: 4px;
	}

	.toolbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-xs);
		padding: var(--space-xs);
		border: var(--border-hairline);
		border-radius: var(--radius-md);
		background: var(--color-canvas);
	}

	.tb-group {
		display: flex;
		gap: 2px;
	}

	.tb-sep {
		width: 1px;
		align-self: stretch;
		background: var(--border-hairline);
	}

	.tb-spacer {
		flex: 1;
	}

	.tb-btn {
		background: transparent;
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		padding: var(--space-xxs) var(--space-xs);
		font: inherit;
		font-size: var(--type-body-sm-size);
		cursor: pointer;
		color: var(--color-ink);
	}

	.tb-btn:hover:not(:disabled) {
		background: var(--color-row-hover);
		border-color: var(--color-hairline);
	}

	.tb-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.body {
		display: grid;
		grid-template-columns: 1fr;
		gap: var(--space-md);
		min-height: 0;
	}

	.body.split {
		grid-template-columns: 1fr 1fr;
	}

	:global(.md-editor-textarea) {
		font-family: var(--font-mono);
		height: 100%;
		resize: vertical;
	}

	.md-editor-preview {
		border: var(--border-hairline);
		border-radius: var(--radius-md);
		padding: var(--space-sm) var(--space-md);
		overflow-y: auto;
		background: var(--color-canvas);
	}

	.drop-hint {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		background: color-mix(in srgb, var(--color-canvas) 85%, transparent);
		border-radius: var(--radius-md);
		pointer-events: none;
	}

	.footer {
		color: var(--color-ink-muted);
		text-align: right;
	}

	@media (max-width: 1100px) {
		.body.split {
			grid-template-columns: 1fr;
		}
	}
</style>
