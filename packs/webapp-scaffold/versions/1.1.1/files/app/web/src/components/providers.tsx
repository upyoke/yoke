"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef, useCallback } from "react";
import { toast } from "sonner";
import { useAuthStore } from "@/store/auth";
import { ApiError } from "@/lib/api";
import { Toaster } from "@/components/ui/sonner";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => {
          // Don't retry on auth failures
          if (error instanceof ApiError && error.status === 401) return false;
          return failureCount < 1;
        },
        staleTime: 30 * 1000,
        refetchOnWindowFocus: false,
      },
    },
  });
}

let queryClient: QueryClient | null = null;
function getQueryClient() {
  if (!queryClient) queryClient = makeQueryClient();
  return queryClient;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const checkAuth = useAuthStore((s) => s.checkAuth);
  const clearUser = useAuthStore((s) => s.clearUser);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const checked = useRef(false);
  const expiredToastShown = useRef(false);

  useEffect(() => {
    if (!checked.current) {
      checked.current = true;
      checkAuth();
    }
  }, [checkAuth]);

  // Global 401 handler — detect session expiry from any failed API call
  const handleQueryError = useCallback(
    (error: Error) => {
      if (
        error instanceof ApiError &&
        error.status === 401 &&
        isAuthenticated &&
        !expiredToastShown.current
      ) {
        expiredToastShown.current = true;
        clearUser();
        toast.error("Session expired — please sign in again", { duration: 5000 });
        // Reset flag after a delay so it can fire again on next login cycle
        setTimeout(() => { expiredToastShown.current = false; }, 6000);
      }
    },
    [isAuthenticated, clearUser],
  );

  const client = getQueryClient();

  // Wire up global error handler via query cache subscription
  useEffect(() => {
    const cache = client.getQueryCache();
    const unsubscribe = cache.subscribe((event) => {
      if (event.type === "updated" && event.query.state.error) {
        handleQueryError(event.query.state.error);
      }
    });
    return unsubscribe;
  }, [client, handleQueryError]);

  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster />
    </QueryClientProvider>
  );
}
