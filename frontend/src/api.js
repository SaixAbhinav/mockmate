// One place that decides where the API lives (ADR 0025).
//
// Empty base (the default) keeps every call relative: in development Vite's
// proxy forwards /api to the backend, and in production Render's static-site
// rewrite forwards it to the API service - the browser sees one origin either
// way, so no CORS is involved.
//
// If that rewrite turns out not to proxy POST bodies, set VITE_API_BASE to the
// API service's URL at build time. Calls then go cross-origin directly and the
// backend's CORS_ORIGINS allows them. No call site changes either way.
const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

export function api(path) {
  return `${API_BASE}${path}`
}
