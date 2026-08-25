// App-wide store — scope (app/repo), the apps list, health polling and the
// toast pill. Replaces the old Alpine.js `Alpine.store("app")` singleton;
// routing itself is no longer handled here — SvelteKit's own router + $page
// take over from the old hash-based parseHash/buildHash.
import { goto } from '$app/navigation';
import { getApps as apiGetApps, refreshApps as apiRefreshApps, getHealth } from '$lib/api/client';
import {
	scopeLabel as scopeLabelFmt,
	findRepo,
	explorerTarget as explorerTargetFmt,
	type AppInfo,
	type ExplorerItem
} from '$lib/utils/format';

const SCOPE_KEY = 'cvg.scope';
const TOAST_MS = 4000;
const HEALTH_POLL_MS = 30_000;

type HealthCheck = { ok: boolean | null };
type Health = {
	qdrant?: HealthCheck;
	neo4j?: HealthCheck;
	mcp_session?: HealthCheck;
	chat?: { configured?: boolean };
};

function readScope(): { app: string; repo: string } {
	if (typeof localStorage === 'undefined') return { app: '', repo: '' };
	try {
		const s = JSON.parse(localStorage.getItem(SCOPE_KEY) || '{}') || {};
		return { app: String(s.app || ''), repo: String(s.repo || '') };
	} catch {
		return { app: '', repo: '' };
	}
}

function writeScope(app: string, repo: string): void {
	try {
		localStorage.setItem(SCOPE_KEY, JSON.stringify({ app, repo }));
	} catch {
		/* localStorage unavailable — scope just won't persist across reloads */
	}
}

class AppStore {
	app = $state('');
	repo = $state('');
	apps = $state<AppInfo[]>([]);
	appsLoaded = $state(false);
	appsError = $state<string | null>(null);

	toast = $state('');
	private toastTimer: ReturnType<typeof setTimeout> | undefined;

	health = $state<Health>({});
	healthLoaded = $state(false);

	/**
	 * Bumped whenever the effective scope actually changes. Views read it in an
	 * $effect to refetch — this replaces the old js/lib/lazy.js `_stale` +
	 * onScopeChange() plumbing, which the SvelteKit port dropped, leaving
	 * /vectors, /graph and /overview showing figures for the previous app.
	 */
	scopeVersion = $state(0);
	private healthTimer: ReturnType<typeof setTimeout> | undefined;

	currentApp = $derived(this.apps.find((a) => a?.name === this.app) || null);
	currentRepo = $derived(
		(this.currentApp?.repos || []).find((r) => r?.name === this.repo) || null
	);
	repos = $derived(this.currentApp?.repos || []);
	scopeLabelText = $derived(scopeLabelFmt(this.app, this.repo));

	constructor() {
		const saved = readScope();
		this.app = saved.app;
		this.repo = saved.repo;
	}

	/** Starts health polling + the apps fetch. Returns a teardown for onMount. */
	init(): () => void {
		this.pollHealth();
		this.loadApps();
		return () => this.stopHealthPolling();
	}

	/** {app, repo} with empty values omitted — spread into API calls. */
	scopeParams(): Record<string, string> {
		const p: Record<string, string> = {};
		if (this.app) p.app = this.app;
		if (this.repo) p.repo = this.repo;
		return p;
	}

	/**
	 * Select an application / repo. Validates against `apps` once loaded
	 * (unknown app -> All + toast; unknown repo -> all repos of the app).
	 * Returns false when the requested scope had to be adjusted.
	 */
	setScope(app: string, repo = ''): boolean {
		app = String(app || '');
		repo = String(repo || '');
		let ok = true;

		if (this.appsLoaded) {
			const found = app ? this.apps.find((a) => a?.name === app) : null;
			if (app && !found) {
				this.showToast(`Unknown application "${app}"`);
				app = '';
				repo = '';
				ok = false;
			} else if (found && repo && !(found.repos || []).some((r) => r?.name === repo)) {
				this.showToast(`Unknown repository "${repo}" in ${app}`);
				repo = '';
				ok = false;
			}
		}
		if (!app) repo = '';

		const changed = app !== this.app || repo !== this.repo;
		this.app = app;
		this.repo = repo;
		writeScope(app, repo);
		// loadApps() re-validates the saved scope on boot; that must not read as
		// a scope change or every view would refetch immediately after mount.
		if (changed) this.scopeVersion++;
		return ok;
	}

	async loadApps(refresh = false): Promise<void> {
		try {
			const data = (refresh ? await apiRefreshApps() : await apiGetApps()) as {
				apps?: AppInfo[];
			};
			this.apps = Array.isArray(data?.apps) ? data.apps : [];
			this.appsError = null;
			this.appsLoaded = true;
			this.setScope(this.app, this.repo);
		} catch (e) {
			this.appsError = String((e as Error)?.message || e);
		}
	}

	// ---- cross-view helpers -------------------------------------------------

	/** Resolve {app, repo, path} for an item {file_path, repo?, rel_path?, app?} or null. */
	explorerTarget(item: ExplorerItem | null) {
		return explorerTargetFmt(this.apps, item, this.app);
	}

	/** Navigate to the file explorer for `item`. Returns false when unresolvable. */
	openInExplorer(item: ExplorerItem | null): boolean {
		const t = this.explorerTarget(item);
		if (!t) return false;
		const q = new URLSearchParams({ repo: t.repo, path: t.path });
		goto(`/apps/${encodeURIComponent(t.app)}/files?${q}`);
		return true;
	}

	/** Navigate to a wiki page. */
	openWikiPage(conceptId: string, { app, repo }: { app?: string; repo?: string } = {}): boolean {
		if (!conceptId) return false;
		const appName =
			app || findRepo(this.apps, repo || '')?.app?.name || this.app || this.apps[0]?.name || '';
		if (!appName) return false;
		const q = new URLSearchParams({ concept: conceptId });
		goto(`/apps/${encodeURIComponent(appName)}/wiki?${q}`);
		return true;
	}

	showToast(msg: string): void {
		this.toast = String(msg || '');
		clearTimeout(this.toastTimer);
		if (this.toast) {
			this.toastTimer = setTimeout(() => {
				this.toast = '';
			}, TOAST_MS);
		}
	}

	// ---- health --------------------------------------------------------------

	async pollHealth(): Promise<void> {
		try {
			this.health = (await getHealth(false)) as Health;
			this.healthLoaded = true;
		} catch {
			this.healthLoaded = true;
		}
		clearTimeout(this.healthTimer);
		this.healthTimer = setTimeout(() => this.pollHealth(), HEALTH_POLL_MS);
	}

	stopHealthPolling(): void {
		clearTimeout(this.healthTimer);
		this.healthTimer = undefined;
	}

	statusOf(ok: boolean | null | undefined): boolean | null {
		return ok === null || ok === undefined ? null : ok;
	}
}

export const appStore = new AppStore();
