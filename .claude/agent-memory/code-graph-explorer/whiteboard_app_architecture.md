---
name: whiteboard_app_architecture
description: High-level map of the white-board (Liveblocks+Convex+Clerk) real-time canvas app, as indexed 2026-07-08
type: project
---

Snapshot of `/Users/ranggaaprilioutama/Repository/poc/white-board` architecture, gathered while
answering a question about its real-time collaborative canvas flow. See
[[project_indexed_target_varies]] for context on why this repo showed up in code-vector-graph's
index at all. Treat file/line specifics as potentially stale — verify before acting on them.

**Why this is worth remembering:** the entry-point chain and Liveblocks wiring pattern
(RoomProvider -> useMutation-wrapped storage ops, presence-driven cursors/drafts) is non-obvious
and took several targeted queries to fully reconstruct; re-deriving it from scratch each time is
wasteful if this repo gets explored again.

**How to apply:** if asked again about this app's canvas/drawing/presence flow, start from
`app/board/[boardId]/page.tsx` -> `components/room.tsx` -> `app/board/[boardId]/_components/canvas.tsx`,
and jump straight to the relevant sub-component below instead of re-searching broadly.

Key entry chain:
- `app/board/[boardId]/page.tsx` — `BoardIdPage`, wraps `<Canvas>` in `<Room roomId={boardId}>`
- `components/room.tsx` — `Room`, sets `RoomProvider` initialPresence (cursor/selection/pencilDraft/penColor)
  and initialStorage (`layers: LiveMap`, `layerIds: LiveList`), wraps children in `ClientSideSuspense`
- `liveblocks.config.ts` — creates the Liveblocks client (`authEndpoint: /api/liveblocks-auth`,
  `throttle: 16`), defines `Presence`/`Storage`/`UserMeta` types, exports all hooks
  (`useStorage`, `useMutation`, `useSelf`, `useOthers*`, `useHistory`, etc.) via `createRoomContext`
- `app/api/liveblocks-auth/route.ts` — POST handler: Clerk `auth()`/`currentUser()`, cross-checks
  Convex `api.board.get` orgId against Clerk orgId, then `liveblocks.prepareSession(...).allow(room, FULL_ACCESS)`

Canvas / layer creation flow (`app/board/[boardId]/_components/canvas.tsx`):
- Toolbar (`toolbar.tsx`) sets `canvasState = {mode: Inserting, layerType}` on tool click
- `onPointerDown` → if `CanvasMode.Pencil`, calls `startDrawing` (sets presence.pencilDraft to first point)
- `onPointerMove` → dispatches by mode: `translateSelectedLayer`, `resizeSelectedLayer`,
  `updateSelectionNet`, `continueDrawing` (appends to presence.pencilDraft), always updates presence.cursor
- `onPointerUp` → if `Inserting`, calls `insertLayer(layerType, point)`; if `Pencil`, calls `insertPath()`
- `insertLayer` (useMutation): `storage.get("layers").set(id, new LiveObject({...}))` +
  `storage.get("layerIds").push(id)`, then sets presence.selection, resets canvasState. Capped at `MAX_LAYERS=100`.
- `insertPath` (useMutation): converts `presence.pencilDraft` via `penPointsToPathLayer` (lib/utils.ts)
  into a `PathLayer`, commits to storage the same way, clears `pencilDraft`
- Rendering: `useStorage(s => s.layerIds)` drives a map over `LayerPreview` (layer-preview.tsx), which
  does `useStorage(root => root.layers.get(id))` and switches on `layer.type` to render
  `Rectangel`/`Ellipse`/`Text`/`Note`/`Path` (types/canvas.ts: `LayerType` enum, `Layer` union)

Presence / live cursors (`cursors-presence.tsx`, `cursor.tsx`):
- `CursorsPresence` = `<Drafts/>` + `<Cursors/>`
- `Cursors`: `useOthersConnectionIds()` → one `<Cursor connectionId>` each; `Cursor` uses
  `useOther(id, u => u.presence.cursor)` + `useOther(id, u => u.info)` to position a `MousePointer2` icon + name label
- `Drafts`: `useOthersMapped(o => ({pencilDraft, penColor: o.presence}), shallow)` → renders a `Path`
  per other user with an active pencilDraft (this is how in-progress pen strokes broadcast live)
- `Participants` (participants.tsx) shows avatars via `useOthers()`/`useSelf()`

Selection/editing utilities:
- `hooks/use-delete-layers.ts` — `useDeleteLayers`, mutation deleting selected layerIds from both
  `layers` map and `layerIds` list
- `hooks/use-selection-bounds.ts` — computes bounding box of selected layers for `SelectionBox`/`SelectionTools`
- `selection-box.tsx` — resize-handle UI (8 handles), only shown for non-Path single selection
- `selection-tools.tsx` — floating toolbar: color picker (`setFill` mutation), `moveToFront`/`moveToBack`
  (reorder `layerIds` LiveList), delete
- `lib/utils.ts` — `pointerEventToCanvasPoint`, `colorToCss`, `resizeBounds`,
  `findIntersectingLayersWithRectangle`, `penPointsToPathLayer`, `getSvgPathFromStroke`
- `path.tsx` — renders freehand strokes using `perfect-freehand`'s `getStroke` + `getSvgPathFromStroke`

Types (`types/canvas.ts`): `LayerType` enum (Rectangle, Ellipse, Path, Text, Note), `Layer` union of
per-type layer shapes (`x,y,width,height,fill,value?`, `PathLayer` adds `points`), `CanvasMode` enum
(None, Pressing, SelectionNet, Translating, Inserting, Resizing, Pencil, Panning), `CanvasState`
discriminated union keyed by `CanvasMode`, `Side` bitmask enum for resize corners.
