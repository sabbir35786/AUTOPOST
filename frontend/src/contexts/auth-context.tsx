"use client"

/*
AUTH INVESTIGATION - FRONTEND AUTH CONTEXT
===========================================

LOGIN FLOW (login function):
1. POST /auth/login → { access_token, token_type }
2. Store access_token in localStorage(TOKEN_STORAGE_KEY)
3. Eagerly set api.defaults.headers.common['Authorization']
4. Call loadUser() → GET /users/me

TOKEN STORAGE:
- Primary: window.localStorage with key TOKEN_STORAGE_KEY (survives page refresh)
- Secondary: React state (token, user)
- Tertiary: api.defaults.headers.common (eager header — beats any race window)

TOKEN ATTACHMENT:
- axios.ts request interceptor reads localStorage on every request (late binding)
- initializeAuth sets the default header immediately on mount (early binding)
- Together they guarantee no request ever goes out without a token

HYDRATION ON MOUNT (initializeAuth):
- Reads token from localStorage
- Sets the Axios default Authorization header immediately
- Validates with GET /users/me (3 retries inside loadUser for cold starts)
- On 401: token is invalid — clear everything
- On other errors: keep token, set user=null (network blip or cold start)

TOKEN REFRESH:
- On every API response, X-New-Token header is checked (in api.ts)
- If present, the new token is stored in localStorage + Axios defaults
- This transparently refreshes expiring tokens without re-login

SECRET_KEY:
- Backend REQUIRES SECRET_KEY as environment variable
- Raises ValueError on startup if not set
- Must be a permanent value in Render env vars (never changes)
*/

import * as React from "react"
import axios from "axios"

import { api } from "@/lib/api"
import { axiosInstance, TOKEN_STORAGE_KEY } from "@/lib/axios"

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
    const maxRetries = 3
    const retryDelay = 2000

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const response = await api.get<User>("/users/me")
        setUser(response.data)
        return
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 401) {
          setUser(null)
          return
        }

        const isNetworkError = axios.isAxiosError(error) && !error.response
        const isServiceUnavailable = axios.isAxiosError(error) &&
          (error.response?.status === 503 || error.response?.status === 502)

        if ((isNetworkError || isServiceUnavailable) && attempt < maxRetries - 1) {
          await new Promise((resolve) => setTimeout(resolve, retryDelay))
          continue
        }

        setUser(null)
      }
    }
  }, [])

  React.useEffect(() => {
    /**
     * initializeAuth — runs once on mount to hydrate auth state from storage.
     *
     * Step 1: Read token from localStorage.
     * Step 2: Eagerly attach it as the Axios default Authorization header.
     *         This ensures even the very first API call (fired before the
     *         per-request interceptor has had a chance to run) carries the token.
     * Step 3: Validate the session with GET /users/me.
     *         loadUser() has built-in 3-attempt retry for Render cold starts.
     * Step 4: On 401 the interceptor in api.ts clears the token + redirects.
     *         On other errors we keep the token and set user=null so the user
     *         isn't silently logged out due to a transient network failure.
     */
    const initializeAuth = async () => {
      const storedToken = typeof window !== "undefined"
        ? window.localStorage.getItem(TOKEN_STORAGE_KEY)
        : null

      if (!storedToken) {
        setIsLoading(false)
        return
      }

      // Hydrate React state
      setToken(storedToken)

      // Eagerly set the default header — interceptors read localStorage
      // per-request (late binding), but this covers the race window between
      // mount and the first interceptor execution.
      axiosInstance.defaults.headers.common["Authorization"] = `Bearer ${storedToken}`

      try {
        await loadUser()
      } finally {
        setIsLoading(false)
      }
    }

    initializeAuth()
  }, [loadUser])

  async function login(email: string, password: string) {
    const response = await api.post<{ access_token: string }>("/auth/login", {
      email,
      password,
    })
    const newToken = response.data.access_token

    // Persist to storage
    window.localStorage.setItem(TOKEN_STORAGE_KEY, newToken)
    // Update React state
    setToken(newToken)
    // Eagerly set the Axios default header for any call that fires before
    // the next interceptor cycle picks up the localStorage value.
    axiosInstance.defaults.headers.common["Authorization"] = `Bearer ${newToken}`

    await loadUser()
  }

  async function register(email: string, password: string, name: string) {
    await api.post("/auth/register", { email, password, name })
    await login(email, password)
  }

  function logout() {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY)
    delete axiosInstance.defaults.headers.common["Authorization"]
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
