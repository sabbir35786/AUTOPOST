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
