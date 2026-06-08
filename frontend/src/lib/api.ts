"use client"

/*
AUTH INVESTIGATION FINDINGS - API CLIENT
======================================

TOKEN ATTACHMENT MECHANISM (lines 103-112):
- Uses Axios request interceptor
- Reads token from: window.localStorage.getItem("auth_token")
- If token exists, calls setAuthHeader() (lines 80-90)
- setAuthHeader() adds: Authorization: Bearer <token>
- Applied to ALL outgoing requests automatically

TIMEOUT CONFIGURATION (line 95):
- Default timeout: 30_000ms (30 seconds)
- test-full-flow overrides to 180_000ms (3 minutes) in social-platform.tsx
- Reason: Render free-tier cold starts + LLM calls + image generation

BACKEND URL RESOLUTION (lines 8-27):
- Localhost: uses http://localhost:8000 or configured backend
- Production: uses /backend proxy on Vercel or configured remote
- Default remote: https://auto-poster-backend.onrender.com

POTENTIAL ISSUES IDENTIFIED:
1. 90-second timeout may be too long, causing slow UX
2. No retry logic for failed requests
3. No token refresh logic - if token expires, requests fail
4. No error handling for 401 responses (could trigger auto-refresh)
*/

import axios, { AxiosHeaders, isAxiosError } from "axios"

const DEFAULT_REMOTE_BACKEND = "https://auto-poster-backend.onrender.com"
const VERCEL_BACKEND_PROXY = "/backend"

function getBackendUrl() {
  const configuredBackend = process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "")

  if (configuredBackend) {
    return configuredBackend
  }

  if (typeof window !== "undefined") {
    // Fallback to proxy only if explicitly configured
    if (configuredBackend === VERCEL_BACKEND_PROXY) {
      return VERCEL_BACKEND_PROXY
    }
  }

  return DEFAULT_REMOTE_BACKEND
}

export const API_BASE_URL = getBackendUrl()

export function getBackendOrigin() {
  const configuredBackend = process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "")
  if (configuredBackend?.startsWith("http")) {
    return configuredBackend
  }
  return DEFAULT_REMOTE_BACKEND
}

export const BACKEND_ORIGIN = typeof window !== "undefined" ? getBackendOrigin() : DEFAULT_REMOTE_BACKEND

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (!isAxiosError(error)) {
    return fallback
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

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000, // 30 seconds - reasonable timeout for API requests
})

function setAuthHeader(config: { headers?: unknown }, token: string) {
  if (!config.headers) {
    config.headers = new AxiosHeaders()
  }
  const headers = config.headers
  if (headers instanceof AxiosHeaders) {
    headers.set("Authorization", `Bearer ${token}`)
    return
  }
  ;(headers as Record<string, string>).Authorization = `Bearer ${token}`
}

function stripFormDataContentType(config: { headers?: unknown; data?: unknown }) {
  if (!(config.data instanceof FormData)) return
  const headers = config.headers
  if (!headers) return
  if (headers instanceof AxiosHeaders) {
    headers.delete("Content-Type")
    return
  }
  delete (headers as Record<string, string>)["Content-Type"]
}

api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem("auth_token")
    if (token) {
      setAuthHeader(config, token)
    }
    stripFormDataContentType(config)
  }
  return config
})

api.interceptors.response.use(
  (response) => {
    // Token refresh: if the backend returned a new token, store it
    const newToken = response.headers?.["x-new-token"]
    if (newToken && typeof window !== "undefined") {
      window.localStorage.setItem("auth_token", newToken)
    }
    return response
  },
  async (error) => {
    // Handle 401 Unauthorized - token expired or invalid
    if (isAxiosError(error) && error.response?.status === 401) {
      // Clear the invalid token from localStorage
      if (typeof window !== "undefined") {
        window.localStorage.removeItem("auth_token")
      }
      // Redirect to login page if not already there
      if (typeof window !== "undefined" && !window.location.pathname.includes("/auth")) {
        window.location.href = "/auth/login"
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
