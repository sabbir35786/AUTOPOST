"use client"

/*
AUTH INVESTIGATION FINDINGS - FRONTEND
======================================

LOGIN RESPONSE HANDLING (lines 56-64):
- Endpoint: POST /auth/login
- Response format: { access_token: string, token_type: "bearer" }
- Token extraction: response.data.access_token
- After receiving token:
  1. Stores in localStorage with key "auth_token" (line 61)
  2. Sets in React state via setToken() (line 62)
  3. Calls loadUser() to fetch user data (line 63)

TOKEN STORAGE:
- Primary storage: window.localStorage with key "auth_token"
- Secondary storage: React state (token, user) in AuthProvider
- On app load (lines 46-53):
  - Reads from localStorage.getItem("auth_token")
  - If token exists, sets it in state and calls loadUser()
  - If no token, sets isLoading to false

TOKEN ATTACHMENT TO API REQUESTS:
- Location: frontend/src/lib/api.ts
- Mechanism: Axios request interceptor (lines 103-112)
- Process:
  1. Interceptor runs before every API request
  2. Reads token from window.localStorage.getItem("auth_token")
  3. If token exists, calls setAuthHeader() (lines 80-90)
  4. setAuthHeader() adds: Authorization: Bearer <token>
- Token is attached to ALL outgoing API requests automatically

POTENTIAL ISSUES IDENTIFIED:
1. Token stored in localStorage (vulnerable to XSS)
2. Token expires after 30 minutes - no refresh token mechanism
3. If token expires, user must re-login (no auto-refresh)
4. No token validation before storage
*/

import * as React from "react"

import { api } from "@/lib/api"

type User = {
  id: number
  email: string
  name: string
  email_verified: boolean
  timezone: string
  plan: string
  created_at: string
}

type AuthContextValue = {
  token: string | null
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string) => Promise<void>
  logout: () => void
}

const AuthContext = React.createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = React.useState<string | null>(null)
  const [user, setUser] = React.useState<User | null>(null)
  const [isLoading, setIsLoading] = React.useState(true)

  const loadUser = React.useCallback(async () => {
    try {
      const response = await api.get<User>("/users/me")
      setUser(response.data)
    } catch {
      window.localStorage.removeItem("auth_token")
      setToken(null)
      setUser(null)
    }
  }, [])

  React.useEffect(() => {
    const storedToken = window.localStorage.getItem("auth_token")
    if (!storedToken) {
      setIsLoading(false)
      return
    }

    setToken(storedToken)
    loadUser().finally(() => setIsLoading(false))
  }, [loadUser])

  async function login(email: string, password: string) {
    const response = await api.post<{ access_token: string }>("/auth/login", {
      email,
      password,
    })
    window.localStorage.setItem("auth_token", response.data.access_token)
    setToken(response.data.access_token)
    await loadUser()
  }

  async function register(email: string, password: string, name: string) {
    await api.post("/auth/register", { email, password, name })
    await login(email, password)
  }

  function logout() {
    window.localStorage.removeItem("auth_token")
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        isLoading,
        isAuthenticated: Boolean(token),
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = React.useContext(AuthContext)
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider")
  }
  return context
}
