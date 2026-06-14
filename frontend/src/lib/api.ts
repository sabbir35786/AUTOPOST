"use client"

/*
AUTH INVESTIGATION FINDINGS - API CLIENT
======================================

TOKEN ATTACHMENT MECHANISM:
- Lives in axios.ts as a request interceptor on axiosInstance.
- Reads token from: window.localStorage.getItem(TOKEN_STORAGE_KEY)
- Adds Authorization: Bearer <token> to every outgoing request.
- FormData Content-Type is stripped there too (browser sets the boundary).

TIMEOUT CONFIGURATION:
- Default timeout: 60_000ms (60 seconds) — elevated to absorb Render
  free-tier cold starts which can take 30-60 s.
- Defined in axios.ts; this file only adds response interceptors.

BACKEND URL RESOLUTION (see axios.ts for full logic):
- NEXT_PUBLIC_API_URL        (canonical — set this in .env.local / Vercel)
- NEXT_PUBLIC_BACKEND_URL    (legacy alias)
- https://autopost-1-ax2p.onrender.com  (hard-coded fallback)

RESPONSE INTERCEPTORS (this file):
1. X-New-Token header — transparently rotates the stored token.
2. 401 — clears localStorage token and redirects to /auth/login.
3. Blob error bodies — parsed to extract JSON detail for user-facing messages.
*/

import { isAxiosError } from "axios"
import { axiosInstance, TOKEN_STORAGE_KEY } from "./axios"

// Re-export helpers so consumers can import from a single place
export { axiosInstance as api }
export const API_BASE_URL: string = (axiosInstance.defaults.baseURL as string) ?? ""

export function getBackendOrigin(): string {
  const base = axiosInstance.defaults.baseURL as string | undefined
  if (base?.startsWith("http")) return base
  return "https://autopost-1-ax2p.onrender.com"
}

export const BACKEND_ORIGIN = typeof window !== "undefined" ? getBackendOrigin() : "https://autopost-1-ax2p.onrender.com"

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (!isAxiosError(error)) {
    return fallback
  }
  if (!error.response) {
    return "The app is starting up. Please wait a moment and try again."
  }
  const detail = error.response?.data?.detail
  if (typeof detail === "string" && detail.trim()) {
    return detail
  }
  if (Array.isArray(detail)) {
    const message = detail
      .map((item) => {
        if (typeof item === "string") return item
        if (item && typeof item === "object" && "msg" in item) {
          return String(item.msg)
        }
        return ""
      })
      .filter(Boolean)
      .join(", ")
    if (message) return message
  }
  const errorMessage = error.response?.data?.error_message
  if (typeof errorMessage === "string" && errorMessage.trim()) {
    return errorMessage
  }
  return fallback
}

// Response interceptors — token refresh + error normalisation
axiosInstance.interceptors.response.use(
  (response) => {
    // Clear cold start timer
    if (typeof window !== "undefined") {
      const timer = (response.config as any)._coldStartTimer
      if (timer) window.clearTimeout(timer)
      window.dispatchEvent(new CustomEvent("backend-cold-start", { detail: false }))
    }

    // Token refresh: if the backend issued a new token, store it and update
    // the default header so subsequent requests don’t need to wait for a
    // localStorage read.
    const newToken = response.headers?.["x-new-token"]
    if (newToken && typeof window !== "undefined") {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, newToken)
      // Eagerly update the default header so the very next call uses it.
      axiosInstance.defaults.headers.common["Authorization"] = `Bearer ${newToken}`
    }
    return response
  },
  async (error) => {
    // Clear cold start timer and handle timeout
    if (typeof window !== "undefined") {
      const timer = (error.config as any)?._coldStartTimer
      if (timer) window.clearTimeout(timer)
      window.dispatchEvent(new CustomEvent("backend-cold-start", { detail: false }))

      if (error.code === "ECONNABORTED" || error.message?.includes("timeout")) {
        window.dispatchEvent(new CustomEvent("backend-timeout"))
      }
    }

    // Handle 401 Unauthorized — token expired or invalid
    if (isAxiosError(error) && error.response?.status === 401) {
      if (typeof window !== "undefined") {
        window.localStorage.removeItem(TOKEN_STORAGE_KEY)
        delete axiosInstance.defaults.headers.common["Authorization"]
        if (!window.location.pathname.includes("/auth")) {
          window.location.href = "/auth/login"
        }
      }
    }

    if (
      isAxiosError(error) &&
      error.config?.responseType === "blob" &&
      error.response?.data instanceof Blob
    ) {
      try {
        const text = await error.response.data.text()
        const parsed = JSON.parse(text) as { detail?: string }
        if (typeof parsed.detail === "string") {
          error.response.data = { detail: parsed.detail }
        }
      } catch {
        // keep original blob body
      }
    }
    return Promise.reject(error)
  },
)
