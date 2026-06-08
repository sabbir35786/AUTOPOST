"use client"

/*
AUTH INVESTIGATION - FRONTEND AUTH CONTEXT
===========================================

LOGIN FLOW (login function):
1. POST /auth/login → { access_token, token_type }
2. Store access_token in localStorage("auth_token")
3. Set token in React state
4. Call loadUser() → GET /users/me

TOKEN STORAGE:
- Primary: window.localStorage with key "auth_token" (survives page refresh)
- Secondary: React state (token, user)

TOKEN ATTACHMENT:
- Axios request interceptor in api.ts reads localStorage("auth_token")
- Adds Authorization: Bearer <token> to every request
- Response interceptor handles 401 by clearing token + redirecting to /login

ROOT CAUSE - USER FORGOTTEN AFTER LOGIN:
- loadUser() was deleting the token on ANY error (network blip, cold start)
- Even after successful login, if loadUser() failed, token was wiped
- FIXED: loadUser() only sets user→null on failure; never touches the token
- Token is only removed on explicit 401 (handled by Axios interceptor)

TOKEN REFRESH:
- On every API response, X-New-Token header is checked
- If present, the new token is stored in localStorage
- This transparently refreshes expiring tokens without re-login

SECRET_KEY:
- Backend now REQUIRES SECRET_KEY as environment variable
- Raises ValueError on startup if not set
- Must be a permanent value in Render env vars (never changes)
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
      // Don't delete the token on non-401 errors (network blip, cold start).
      // The Axios interceptor in api.ts handles 401 by clearing token + redirecting.
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
