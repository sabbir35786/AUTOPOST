"use client"

import axios from "axios"

const DEFAULT_REMOTE_BACKEND = "https://autopost-qwgw.onrender.com"
const VERCEL_BACKEND_PROXY = "/backend"

function getBackendUrl() {
  const configuredBackend = process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "")

  if (typeof window !== "undefined") {
    const isLocalhost = ["localhost", "127.0.0.1"].includes(window.location.hostname)
    if (isLocalhost) {
      return configuredBackend || "http://localhost:8000"
    }

    const configuredForLocalhost =
      configuredBackend?.startsWith("http://localhost") ||
      configuredBackend?.startsWith("http://127.0.0.1")

    if (!configuredBackend || configuredBackend === DEFAULT_REMOTE_BACKEND || configuredForLocalhost) {
      return VERCEL_BACKEND_PROXY
    }
  }

  return configuredBackend || DEFAULT_REMOTE_BACKEND
}

export const API_BASE_URL = getBackendUrl()

export function getBackendOrigin() {
  const configuredBackend = process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "")
  if (configuredBackend?.startsWith("http")) {
    return configuredBackend
  }
  if (typeof window !== "undefined") {
    const isLocalhost = ["localhost", "127.0.0.1"].includes(window.location.hostname)
    if (isLocalhost) {
      return configuredBackend || "http://localhost:8000"
    }
  }
  return DEFAULT_REMOTE_BACKEND
}

export const BACKEND_ORIGIN = typeof window !== "undefined" ? getBackendOrigin() : DEFAULT_REMOTE_BACKEND

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError(error)) {
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
  timeout: 90_000, // Render free-tier cold starts can take 30-60s
})

api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem("auth_token")
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})
