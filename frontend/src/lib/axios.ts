/**
 * axios.ts — Centralized Axios instance + token injection
 *
 * WHY THIS FILE EXISTS:
 * ---------------------
 * Railway spins down inactive deployments. The first request after a cold
 * start can take 60-90 seconds. A default 5-10 s timeout would cause silent
 * failures. We set 120 s here so that the backend has time to boot before the
 * request is abandoned.
 *
 * BASE URL RESOLUTION ORDER:
 *   1. NEXT_PUBLIC_API_URL  (canonical — set this one)
 *   2. NEXT_PUBLIC_BACKEND_URL  (legacy alias, kept for backward-compat)
 *   3. Hard-coded Render fallback  (safety net — should never be needed in prod)
 *
 * TOKEN STORAGE KEY:
 *   Defined once here and imported everywhere so a key rename is a one-line
 *   change. The existing app uses "auth_token" — do NOT change this without
 *   a migration step or all current users will be silently logged out.
 */

import axios from "axios"

const FALLBACK_BACKEND = "https://auto-poster-backend-production.up.railway.app"

/**
 * Single source of truth for the localStorage key that stores the JWT.
 * Import this constant instead of hardcoding the string "auth_token".
 */
export const TOKEN_STORAGE_KEY = "auth_token"

function resolveBaseUrl(): string {
  // Prefer the new canonical variable; fall back to the legacy alias.
  const url =
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.NEXT_PUBLIC_BACKEND_URL ||
    FALLBACK_BACKEND

  // Strip trailing slash so paths like /auth/login work without double-slashes.
  return url.replace(/\/$/, "")
}

/**
 * The single, shared Axios instance for all API requests.
 *
 * Import this in api.ts (or anywhere else) instead of calling axios.create()
 * a second time, so all interceptors and config stay in one place.
 */
export const axiosInstance = axios.create({
  baseURL: resolveBaseUrl(),

  // 120 s — Railway cold starts can take 60-90 s. We give extra headroom so
  // the backend has time to boot before we give up and show the error banner.
  // Individual call sites can still pass { timeout: N } to override per-request.
  timeout: 120_000,

  headers: {
    "Content-Type": "application/json",
  },
})

// ---------------------------------------------------------------------------
// Request interceptor — Dynamic token injection
//
// Reads the JWT from localStorage on every request so that:
//   a) Tokens written after initial page load are picked up automatically.
//   b) Token refreshes (via X-New-Token header) are used on the very next call.
//   c) The token never has to be manually threaded through call-sites.
//
// FormData uploads: Content-Type must NOT be set (the browser sets the
// multipart boundary). We strip it here so upload routes work correctly.
// ---------------------------------------------------------------------------
axiosInstance.interceptors.request.use(
  (config) => {
    if (typeof window === "undefined") return config // SSR — skip

    const token = window.localStorage.getItem(TOKEN_STORAGE_KEY)
    if (token) {
      config.headers = config.headers ?? {}
      config.headers["Authorization"] = `Bearer ${token}`
    }

    // Strip Content-Type for multipart/form-data so the browser can set the
    // boundary parameter automatically.
    if (config.data instanceof FormData) {
      delete (config.headers as Record<string, string>)["Content-Type"]
    }

    // Start cold start timer — show the "waking up" banner after 3 s
    const timer = window.setTimeout(() => {
      window.dispatchEvent(new CustomEvent("backend-cold-start", { detail: true }))
    }, 3000)
    ;(config as any)._coldStartTimer = timer

    return config
  },
  (error) => Promise.reject(error),
)

export default axiosInstance
