"use client";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Toaster, toast } from "sonner";

import { TooltipProvider } from "@/components/ui/overlay";
import { ApiError } from "@/lib/api/client";
import { onApiReachabilityChange } from "@/lib/api/health";
import { AuthProvider, tokenSource, useAuth } from "@/lib/auth";
import { installGlobalErrorLogging, logger } from "@/lib/logger";

function TokenBridge() {
  const { getToken, signOut } = useAuth();
  const router = useRouter();
  useEffect(() => {
    tokenSource.get = getToken;
    tokenSource.onUnauthorized = () => {
      void signOut().then(() => router.replace("/login"));
    };
  }, [getToken, signOut, router]);
  return null;
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        refetchOnWindowFocus: true,
        // Retry server errors and network blips (status 0); never retry 4xx.
        retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
        retryDelay: (n) => Math.min(1000 * 2 ** n, 10_000),
      },
    },
    queryCache: new QueryCache({
      onError: (err, query) => {
        if (err instanceof ApiError && err.status === 429) {
          toast.warning("You're going a bit fast.", { description: `Try again in ${err.retryAfter ?? 30}s.` });
        } else if (!(err instanceof ApiError)) {
          logger.error("query failed", err, { queryKey: JSON.stringify(query.queryKey).slice(0, 200) });
        }
      },
    }),
    mutationCache: new MutationCache({
      onError: (err) => {
        if (!(err instanceof ApiError)) logger.error("mutation failed", err);
      },
    }),
  });
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(makeClient);
  useEffect(() => installGlobalErrorLogging(), []);
  useEffect(
    () =>
      onApiReachabilityChange((up) => {
        if (up) {
          void client.invalidateQueries(); // catch up on everything missed while the API was down
          void logger.flush();
        } else {
          logger.warn("API unreachable");
        }
      }),
    [client],
  );
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <AuthProvider>
        <TokenBridge />
        <QueryClientProvider client={client}>
          <TooltipProvider>
            {children}
            <Toaster position="bottom-right" richColors closeButton />
          </TooltipProvider>
        </QueryClientProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
