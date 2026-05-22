"use client"

import * as React from "react"

import { api } from "@/lib/api"

type User = {
  id: number
  email: string
  name: string
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
