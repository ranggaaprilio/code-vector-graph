<script lang="ts">
	import { tick, onMount } from 'svelte';
	import { page as pageState } from '$app/state';
	import { goto } from '$app/navigation';
	import { appStore } from '$lib/stores/app.svelte';
	import { getChatConfig } from '$lib/api/client';
	import { chatStream, type ChatSource } from '$lib/api/chatStream';
	import { renderMarkdown, highlightWithin, locationStr, isWiki } from '$lib/utils/format';
	import { SectionEyebrow, Button, Select, TextArea, Toast } from '$lib/components/ds';
	// Light syntax theme: a dark slab would be the only dark surface on the page.
	import 'highlight.js/styles/github.css';

	type Role = 'user' | 'assistant' | 'system';
	type Msg = {
		id: number;
		role: Role;
		content: string;
		streaming?: boolean;
		sources?: ChatSource[];
		renderedHtml?: string;
	};

	const GENERIC_SUGGESTIONS = [
		'How does authentication work in this codebase?',
		'Where is the main entry point and what does it do?',
		'What classes are defined and how do they relate?',
		'Explain the data flow from input to storage.'
	];

	const RENDER_THROTTLE_MS = 120;

	let messages = $state<Msg[]>([]);
	let input = $state('');
	let streaming = $state(false);
	let streamCtrl: AbortController | null = null;
	let statusMsg = $state('');
	let mode = $state('hybrid');
	let topK = $state(10);
	let showOptions = $state(false);
	let error = $state<string | null>(null);

	let config = $state<{ configured?: boolean; reason?: string; provider?: string; model?: string } | null>(
		null
	);
	let configLoading = $state(true);

	let threadEl: HTMLDivElement | undefined = $state();
	let composerEl: HTMLTextAreaElement | undefined = $state();
	/** Autoscroll only while the reader is actually at the bottom. */
	let pinnedToBottom = $state(true);

	getChatConfig()
		.then((c) => (config = c as typeof config))
		.catch((e) => (config = { configured: false, reason: String(e?.message || e) }))
		.finally(() => (configLoading = false));

	const disabledReason = $derived.by(() => {
		if (configLoading) return '';
		if (config && config.configured === false) return config.reason || 'Chat is not configured.';
		if (appStore.health?.mcp_session?.ok === false) {
			return 'The MCP session is not running — search results are unavailable.';
		}
		return '';
	});

	const suggestions = $derived.by(() => {
		const app = appStore.currentApp;
		if (!app) return GENERIC_SUGGESTIONS;
		const repos = (app.repos || []).map((r) => r.name);
		return [
			`What does the ${app.name} application do?`,
			`Explain the architecture of ${app.name}.`,
			appStore.repo
				? `What are the main entry points of ${appStore.repo}?`
				: repos.length > 1
					? `How do ${repos.slice(0, 2).join(' and ')} interact?`
					: `What are the main entry points of ${app.name}?`,
			'What are the main entry points?'
		];
	});

	let lastScope = appStore.scopeLabelText;
	$effect(() => {
		const label = appStore.scopeLabelText;
		if (label !== lastScope && messages.length) {
			messages.push({ id: Date.now(), role: 'system', content: `Scope changed to ${label}.` });
			scrollToBottom();
		}
		lastScope = label;
	});

	/** Yanking the view down while someone is reading back is hostile, so a
	 *  stream only autoscrolls when the thread is already at the bottom. */
	// Hand-off from the file explorer arrives as ?file=<repo-relative path>.
	// The question is prefilled, never auto-sent — sending costs the user tokens.
	onMount(() => {
		const file = pageState.url.searchParams.get('file');
		if (!file) return;
		input = `Explain ${file} — what is it responsible for and what calls into it?`;
		composerEl?.focus();
	});

	async function scrollToBottom(force = false) {
		await tick();
		if (!threadEl) return;
		if (!force && !pinnedToBottom) return;
		threadEl.scrollTop = threadEl.scrollHeight;
		pinnedToBottom = true;
	}

	function onThreadScroll() {
		if (!threadEl) return;
		const gap = threadEl.scrollHeight - threadEl.scrollTop - threadEl.clientHeight;
		pinnedToBottom = gap < 48;
	}

	function findMsg(id: number): Msg | undefined {
		return messages.find((m) => m.id === id);
	}

	async function renderAssistant(msg: Msg | undefined) {
		if (!msg) return;
		msg.renderedHtml = renderMarkdown(msg.content);
		await tick();
		document.querySelectorAll('.chat-assistant-bubble').forEach((el) => highlightWithin(el));
	}

	async function send() {
		const msg = input.trim();
		if (!msg || streaming || disabledReason) return;
		input = '';
		error = null;

		messages.push({ id: Date.now(), role: 'user', content: msg });
		const assistantId = Date.now() + 1;
		messages.push({ id: assistantId, role: 'assistant', content: '', sources: [], streaming: true });
		scrollToBottom(true);

		streaming = true;
		statusMsg = 'Connecting…';

		const history = messages
			.slice(0, -2)
			.filter((m) => m.role === 'user' || m.role === 'assistant')
			.map((m) => ({ role: m.role, content: m.content }));

		let lastRender = 0;
		const maybeRender = (force: boolean) => {
			const now = Date.now();
			if (force || now - lastRender >= RENDER_THROTTLE_MS) {
				lastRender = now;
				renderAssistant(findMsg(assistantId));
			}
		};

		streamCtrl = chatStream(
			{
				message: msg,
				history: history.slice(-10),
				options: { mode, top_k: topK, ...appStore.scopeParams() }
			},
			{
				onStatus: (text) => {
					statusMsg = text;
				},
				onToken: (text) => {
					const m = findMsg(assistantId);
					if (!m) return;
					m.content += text;
					m.streaming = true;
					maybeRender(false);
					scrollToBottom();
				},
				onSources: (srcs) => {
					const m = findMsg(assistantId);
					if (m) m.sources = srcs || [];
				},
				onDone: () => {
					const m = findMsg(assistantId);
					if (m) m.streaming = false;
					streaming = false;
					statusMsg = '';
					streamCtrl = null;
					maybeRender(true);
					scrollToBottom();
				},
				onError: (text) => {
					const m = findMsg(assistantId);
					if (m) {
						m.content += `\n\n_Error: ${text}_`;
						m.streaming = false;
					}
					streaming = false;
					statusMsg = '';
					error = text;
					streamCtrl = null;
					maybeRender(true);
					scrollToBottom();
				}
			}
		);
	}

	function stop() {
		streamCtrl?.abort();
		streaming = false;
		statusMsg = '';
		const last = messages[messages.length - 1];
		if (last) last.streaming = false;
	}

	function useSuggestion(s: string) {
		input = s;
		tick().then(() => composerEl?.focus());
	}

	function clearChat() {
		messages = [];
		error = null;
		statusMsg = '';
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			send();
		}
	}

	/** Jump to a source's location in the file explorer, or the Vectors search as a fallback. */
	function openSource(s: ChatSource) {
		if (appStore.openInExplorer(s as { file_path?: string; repo?: string; app?: string })) return;
		// A citation we can't pin to an indexed repo is still searchable — send
		// it to Vectors instead of dead-ending on a toast.
		const path = (s as { file_path?: string }).file_path || '';
		const name = path.split('/').pop() || path;
		if (name) {
			const q = new URLSearchParams({ q: name, ...appStore.scopeParams() });
			goto(`/vectors?${q}`);
			return;
		}
		appStore.showToast(`Couldn't resolve "${path}" to a repo.`);
	}
</script>

<SectionEyebrow title="AI CHAT" tint="salmon" />

<div class="chat">
	<div class="header">
		<h2 class="ds-h2">AI Code Assistant</h2>
		<span class="ds-caption">Scope: {appStore.scopeLabelText}</span>
		{#if !appStore.app}
			<span class="ds-caption hint">— select an application for focused answers</span>
		{/if}
		<div class="spacer"></div>
		<Button variant="secondary" onclick={() => (showOptions = !showOptions)}>Options</Button>
		<Button variant="secondary" onclick={clearChat}>Clear</Button>
	</div>

	{#if !configLoading && disabledReason}
		<div class="banner ds-body-sm">{disabledReason}</div>
	{/if}

	{#if showOptions}
		<div class="options ds-body-sm">
			<label>
				Mode:
				<Select bind:value={mode} class="inline-select">
					<option value="hybrid">hybrid</option>
					<option value="vector">vector</option>
					<option value="graph">graph</option>
				</Select>
			</label>
			<label>
				Top-K:
				<input type="number" min="1" max="30" bind:value={topK} class="ds-input inline-number" />
			</label>
			{#if config?.provider}
				<span class="provider">{config.provider} · {config.model || ''}</span>
			{/if}
		</div>
	{/if}

	<div class="thread" bind:this={threadEl} onscroll={onThreadScroll}>
		{#if messages.length === 0}
			<div class="empty">
				<p class="ds-body-sm">Ask anything about the indexed codebase.</p>
				<div class="suggestions">
					{#each suggestions as s (s)}
						<Button variant="secondary" onclick={() => useSuggestion(s)}>{s}</Button>
					{/each}
				</div>
			</div>
		{/if}

		{#each messages as msg (msg.id)}
			{#if msg.role === 'system'}
				<div class="system-note ds-caption">{msg.content}</div>
			{:else if msg.role === 'user'}
				<div class="row row-user">
					<div class="bubble bubble-user ds-body-sm">{msg.content}</div>
				</div>
			{:else}
				<div class="row row-assistant">
					<div class="assistant-block">
						<div
							class="bubble bubble-assistant chat-assistant-bubble ds-body-sm"
							role="status"
							aria-live="polite"
							aria-busy={msg.streaming || undefined}
						>
							{#if msg.streaming && !msg.content}
								<div class="thinking">
									<span class="typing-dots"><span></span><span></span><span></span></span>
									{#if statusMsg}<span class="ds-caption">{statusMsg}</span>{/if}
								</div>
							{:else if msg.content}
								{#if msg.renderedHtml}
									<div class="prose ds-prose">{@html msg.renderedHtml}</div>
								{:else}
									<div class="plain">{msg.content}</div>
								{/if}
								{#if msg.streaming}<span class="cursor"></span>{/if}
							{/if}
							{#if msg.streaming && msg.content && statusMsg}
								<div class="ds-caption status-inline">{statusMsg}</div>
							{/if}
						</div>

						{#if msg.sources && msg.sources.length}
							<details class="sources">
								<summary class="ds-caption">Sources ({msg.sources.length})</summary>
								<div class="sources-list">
									{#each msg.sources as s, i (i)}
										<button
											type="button"
											class="source-link ds-mono ds-body-sm"
											onclick={() => openSource(s)}
										>
											{#if isWiki(s as Record<string, unknown>)}<span class="wiki-tag">wiki</span
												>{/if}
											{locationStr(s as { file_path?: string; start_line?: number; end_line?: number })}
										</button>
									{/each}
								</div>
							</details>
						{/if}
					</div>
				</div>
			{/if}
		{/each}
	</div>

	{#if messages.length && !pinnedToBottom}
		<div class="jump-row">
			<Button variant="secondary" onclick={() => scrollToBottom(true)}>&darr; Jump to latest</Button>
		</div>
	{/if}

	{#if error}
		<div class="error-bar ds-body-sm">
			<span>{error}</span>
			<button type="button" class="dismiss" onclick={() => (error = null)}>&times;</button>
		</div>
	{/if}

	<div class="composer">
		<TextArea
			bind:value={input}
			bind:el={composerEl}
			onkeydown={onKeydown}
			placeholder="Ask a question about the codebase… (Enter to send, Shift+Enter for newline)"
			rows={2}
			disabled={streaming || !!disabledReason}
			class="composer-input"
		/>
		{#if !streaming}
			<Button onclick={send} disabled={!input.trim() || !!disabledReason}>Send</Button>
		{:else}
			<Button variant="secondary" onclick={stop}>Stop</Button>
		{/if}
	</div>
</div>

<style>
	.chat {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
	}

	.header {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-md) var(--space-lg);
		border-bottom: var(--border-hairline);
		flex-wrap: wrap;
	}

	.hint {
		color: var(--color-ink-muted);
	}

	.spacer {
		flex: 1;
	}

	.banner {
		padding: var(--space-sm) var(--space-lg);
		background: var(--color-yellow-sticker);
		border-bottom: var(--border-hairline);
	}

	.options {
		display: flex;
		gap: var(--space-lg);
		align-items: center;
		padding: var(--space-sm) var(--space-lg);
		border-bottom: var(--border-hairline);
		flex-wrap: wrap;
	}

	.options :global(.inline-select) {
		width: auto;
		display: inline-block;
		margin-left: var(--space-xs);
	}

	.inline-number {
		width: 4rem;
		display: inline-block;
		margin-left: var(--space-xs);
	}

	.provider {
		margin-left: auto;
		color: var(--color-ink-muted);
	}

	.thread {
		flex: 1;
		overflow-y: auto;
		padding: var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.empty {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-lg);
		text-align: center;
	}

	.suggestions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
		justify-content: center;
		max-width: 32rem;
	}

	.system-note {
		text-align: center;
		color: var(--color-ink-muted);
		font-style: italic;
	}

	.row {
		display: flex;
	}

	.row-user {
		justify-content: flex-end;
	}

	.row-assistant {
		justify-content: flex-start;
	}

	.assistant-block {
		max-width: 34rem;
	}

	.bubble {
		border: var(--border-hairline);
		padding: var(--space-sm) var(--space-md);
		max-width: 34rem;
	}

	.bubble-user {
		background: var(--color-frame-ink);
		color: var(--color-on-primary);
		font-family: var(--font-heading);
	}

	.bubble-assistant {
		background: var(--color-canvas);
		color: var(--color-ink);
	}

	.prose :global(p) {
		margin: 0 0 var(--space-xs) 0;
	}

	.prose :global(pre) {
		overflow-x: auto;
		padding: var(--space-xs);
		border: var(--border-hairline);
	}

	.plain {
		white-space: pre-wrap;
	}

	.cursor {
		display: inline-block;
		width: 2px;
		height: 1em;
		background: var(--color-ink);
		margin-left: 2px;
		vertical-align: text-bottom;
		animation: blink 1s step-start infinite;
	}

	@keyframes blink {
		50% {
			opacity: 0;
		}
	}

	.thinking {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.typing-dots {
		display: inline-flex;
		gap: 3px;
	}

	.typing-dots span {
		width: 5px;
		height: 5px;
		background: var(--color-ink);
		display: inline-block;
		animation: blink 1.2s infinite;
	}

	.typing-dots span:nth-child(2) {
		animation-delay: 0.2s;
	}

	.typing-dots span:nth-child(3) {
		animation-delay: 0.4s;
	}

	.status-inline {
		margin-top: var(--space-xs);
	}

	.sources {
		margin-top: var(--space-xs);
	}

	.sources-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding-left: var(--space-sm);
		border-left: var(--border-hairline);
		margin-top: var(--space-xs);
	}

	.source-link {
		background: none;
		border: none;
		padding: 0;
		color: var(--color-link);
		text-decoration: underline;
		text-align: left;
		cursor: pointer;
		display: flex;
		gap: var(--space-xs);
		align-items: center;
	}

	.wiki-tag {
		border: var(--border-hairline);
		padding: 0 3px;
		text-decoration: none;
	}

	.jump-row {
		display: flex;
		justify-content: center;
		padding: var(--space-s) var(--space-lg) 0;
	}

	.error-bar {
		display: flex;
		justify-content: space-between;
		padding: var(--space-sm) var(--space-lg);
		background: var(--color-primary);
		color: var(--color-on-primary);
	}

	.dismiss {
		background: none;
		border: none;
		color: var(--color-on-primary);
		cursor: pointer;
		font-size: 1rem;
	}

	.composer {
		display: flex;
		gap: var(--space-sm);
		align-items: flex-end;
		padding: var(--space-md) var(--space-lg);
		border-top: var(--border-hairline);
	}

	.composer :global(.composer-input) {
		flex: 1;
	}
</style>
