"use client";

import { create } from "zustand";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/types";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  /** Session ID from login response (needed for SSE auth) */
  sessionId: string | null;
  setUser: (user: User, sessionId?: string) => void;
  clearUser: () => void;
  checkAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  sessionId: null,

  setUser: (user, sessionId) => set({ user, isAuthenticated: true, isLoading: false, sessionId: sessionId ?? null }),

  clearUser: () => set({ user: null, isAuthenticated: false, isLoading: false, sessionId: null }),

  checkAuth: async () => {
    try {
      const data = await apiGet<{ user: User }>("/api/auth/me");
      set({ user: data.user, isAuthenticated: true, isLoading: false });
    } catch {
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },
}));
