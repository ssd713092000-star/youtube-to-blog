"use client";

/**
 * Safe "resume the pipeline" actions (review, publish, cancel, retry).
 * - One Idempotency-Key per user intent, reused if the same request is retried after a network error,
 *   so a double click or retry never resumes the graph twice (the backend replays the first response).
 * - Sends expected_checkpoint_id; on 409 (job changed under us) it refetches and tells the user.
 * - Keeps the button locked from click until the job leaves its paused state.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { ApiError, newIdempotencyKey } from "@/lib/api/client";
import { qk } from "@/lib/hooks/queries";
import { logger } from "@/lib/logger";

export function useResumeAction<TArgs>(
  jobId: string,
  action: (args: TArgs, idempotencyKey: string) => Promise<unknown>,
  opts: { onSuccess?: () => void; label?: string } = {},
) {
  const qc = useQueryClient();
  const [pending, setPending] = useState(false);
  const keyRef = useRef<{ args: string; key: string } | null>(null);

  const run = useCallback(
    async (args: TArgs): Promise<boolean> => {
      if (pending) return false;
      const argsKey = JSON.stringify(args);
      if (!keyRef.current || keyRef.current.args !== argsKey) keyRef.current = { args: argsKey, key: newIdempotencyKey() };
      setPending(true);
      try {
        await action(args, keyRef.current.key);
        keyRef.current = null;
        await qc.invalidateQueries({ queryKey: qk.job(jobId) });
        void qc.invalidateQueries({ queryKey: ["jobs"] });
        opts.onSuccess?.();
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          keyRef.current = null;
          toast.warning("This job changed since you loaded it.", { description: "We refreshed it for you." });
          await qc.invalidateQueries({ queryKey: qk.job(jobId) });
          await qc.invalidateQueries({ queryKey: qk.review(jobId) });
          await qc.invalidateQueries({ queryKey: qk.publishRequest(jobId) });
        } else if (e instanceof ApiError && e.status < 500) {
          keyRef.current = null;
          toast.error(e.message);
        } else {
          // Network/5xx: keep the same key so a retry is deduplicated server-side.
          logger.error(`${opts.label ?? "action"} failed`, e, { jobId });
          toast.error("Couldn't reach the server.", {
            description: e instanceof ApiError && e.requestId ? `Request ID ${e.requestId}` : undefined,
            action: { label: "Retry", onClick: () => void run(args) },
          });
        }
        setPending(false);
        return false;
      }
      setPending(false);
      return true;
    },
    [action, jobId, opts, pending, qc],
  );

  return { run, pending };
}
