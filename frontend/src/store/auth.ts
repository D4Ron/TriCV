import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '@/types'

const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  user: User | null
  login: (email: string, password: string) => Promise<void>
  refresh: () => Promise<boolean>
  loadUser: () => Promise<void>
  logout: () => void
}

/**
 * Tokens live in localStorage so a reload keeps the session. That is XSS-
 * readable by design — the trade documented in the README — and the reason the
 * access token is short-lived.
 */
export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,

      login: async (email, password) => {
        const response = await fetch(`${API_URL}/api/v1/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password }),
        })
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          throw new Error(
            (body as { detail?: string } | null)?.detail ?? 'Invalid email or password',
          )
        }
        const data = (await response.json()) as { access_token: string; refresh_token: string }
        set({ accessToken: data.access_token, refreshToken: data.refresh_token })
        await get().loadUser()
      },

      refresh: async () => {
        const token = get().refreshToken
        if (!token) return false
        const response = await fetch(`${API_URL}/api/v1/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: token }),
        })
        if (!response.ok) return false
        const data = (await response.json()) as { access_token: string; refresh_token: string }
        set({ accessToken: data.access_token, refreshToken: data.refresh_token })
        return true
      },

      loadUser: async () => {
        const token = get().accessToken
        if (!token) return
        const response = await fetch(`${API_URL}/api/v1/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (response.ok) {
          set({ user: (await response.json()) as User })
        }
      },

      logout: () => set({ accessToken: null, refreshToken: null, user: null }),
    }),
    {
      name: 'tricv-auth',
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
      }),
    },
  ),
)
