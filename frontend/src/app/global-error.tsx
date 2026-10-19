"use client";

import { useEffect } from "react";

import { logger } from "@/lib/logger";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    logger.error("root layout error", error, { digest: error.digest });
    void logger.flush(true);
  }, [error]);
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", display: "grid", placeItems: "center", minHeight: "100vh", margin: 0 }}>
        <div style={{ textAlign: "center" }}>
          <h1 style={{ fontSize: 18 }}>Tube2Dev hit an unexpected error.</h1>
          <button onClick={reset} style={{ marginTop: 12, padding: "8px 14px", borderRadius: 6, border: "1px solid #d6d3d1", background: "#fff" }}>
            Reload
          </button>
        </div>
      </body>
    </html>
  );
}
