"use client"

import axios from "axios"

let resolvedBackend = process.env.NEXT_PUBLIC_BACKEND_URL;
if (!resolvedBackend) {
  if (typeof window !== "undefined" && window.location.hostname === "localhost") {
    resolvedBackend = "http://localhost:8000";
  } else {
    resolvedBackend = "https://autopost-qwgw.onrender.com";
  }
}
export const API_BASE_URL = resolvedBackend.replace(/\/$/, "");

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
