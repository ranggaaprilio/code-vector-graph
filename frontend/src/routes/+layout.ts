// Pure client-rendered SPA — FastAPI serves the static build and falls back
// to index.html for every client-side route (see api/app.py's catch-all).
export const ssr = false;
export const prerender = false;
