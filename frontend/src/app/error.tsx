"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { logger } from "@/lib/logger";

export default function ErrorBoundary({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    logger.error("render error", error, { digest: error.digest });
  }, [error]);
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 px-6 text-center" role="alert">
      <h1 className="text-lg font-semibold">Something broke on this page.</h1>
      <p className="max-w-md text-sm text-fg-subtle">It's been reported. You can try again, or head back to the dashboard.</p>
      {error.digest && <p className="font-mono text-[11px] text-fg-faint">ref {error.digest}</p>}
      <div className="flex gap-2">
        <Button variant="primary" onClick={reset}>
          Try again
        </Button>
        <Button onClick={() => (window.location.href = "/dashboard")}>Dashboard</Button>
      </div>
    </div>
  );
}
