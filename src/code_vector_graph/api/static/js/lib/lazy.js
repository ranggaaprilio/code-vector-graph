// Lazy-activation wiring shared by every view component.
//
// All views are mounted at page load (they are `x-show` blocks in index.html),
// so none of them should fetch anything in `init()`. Instead each view calls
// `bindLazyView(this, "<screen id>")` from its `init()` and implements:
//
//   activate()        – called every time the view becomes visible; the view
//                       runs its first-load work once (guarded by `_activated`)
//                       and then `consumePrefill()`.
//   onScopeChange()   – called when the app/repo scope changes (once per change,
//                       even though both `app` and `repo` may change together).
//   consumePrefill()  – reads + clears `$store.app.prefill[<id>]` when present.
//
// Screen ids: "apps", "app", "vectors", "graph", "chat", "overview".

export function bindLazyView(ctx, id) {
  const store = ctx.$store.app;

  ctx.$watch("$store.app.screen", (screen) => {
    if (screen === id) ctx.activate();
  });

  // `scopeKey` is a single derived string so a combined app+repo change fires once.
  ctx.$watch("$store.app.scopeKey", () => {
    ctx.onScopeChange?.();
  });

  ctx.$watch(`$store.app.prefill.${id}`, (p) => {
    if (p && store.screen === id) ctx.consumePrefill?.();
  });

  if (store.screen === id) ctx.activate();
}

/** True when the given screen id is the one currently shown. */
export function isActiveScreen(ctx, id) {
  return ctx.$store.app.screen === id;
}
