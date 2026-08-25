/**
 * Base URL for the API. Empty means "same origin as this page".
 *
 * The dev server proxies /api and /widget.js to the backend (see
 * vite.config.ts), so relative URLs work locally *and* through a tunnel such
 * as Cloudflare or ngrok, where the visitor's localhost is not ours. The
 * Docker image passes VITE_API_URL explicitly at build time for nginx.
 *
 * This lives in its own module because both lib/api.ts and store/auth.ts need
 * it, and api.ts imports the auth store — so exporting it from there would
 * make the cycle load-bearing. It also once drifted: the store kept a
 * hardcoded localhost:8000 fallback after api.ts moved to same-origin, which
 * broke sign-in for anyone reaching the app through a tunnel.
 */
const configured = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

/**
 * A localhost API URL is only meaningful to a browser running on the same
 * machine. When the page itself was served from somewhere else — a tunnel, a
 * LAN address, a real domain — that URL points at the *visitor's* computer,
 * where nothing is listening; and from an https page the browser blocks the
 * plain-http request outright as mixed content. Same-origin is the only value
 * with a chance of working, so prefer it.
 *
 * This is a guard, not the mechanism: the dev server is configured to leave
 * VITE_API_URL unset precisely so the normal path is same-origin.
 */
function isLocal(host: string): boolean {
  return host === 'localhost' || host === '127.0.0.1' || host === '[::1]'
}

function resolveApiUrl(): string {
  if (!configured) return ''
  if (typeof window === 'undefined') return configured
  try {
    if (isLocal(new URL(configured, window.location.href).hostname) && !isLocal(window.location.hostname)) {
      return ''
    }
  } catch {
    return ''
  }
  return configured
}

export const API_URL = resolveApiUrl()

export const API_BASE = `${API_URL}/api/v1`
