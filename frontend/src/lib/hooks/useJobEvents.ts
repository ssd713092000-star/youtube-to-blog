"use client";

/**
 * Live job progress over Server-Sent Events.
 *
 * Uses fetch-event-source (EventSource can't send an Authorization header). On reconnect the library
 * sends Last-Event-ID, and the backend replays everything after it from the job_events table, so
 * nothing is missed. Every event invalidates/patches the TanStack Query cache; if the stream can't
 * connect it falls back to polling every 5s.
 */
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { setApiReachable } from "@/lib/api/health";
import { tokenSource } from "@/lib/auth";
import { config } from "@/lib/config";
import { qk } from "@/lib/hooks/queries";
import { logger } from "@/lib/logger";

export type ConnectionState = "connecting" | "live" | "reconnecting" | "offline";

export interface JobEvent {
  id: number;
  type: string;
  at: string;
  data: Record<string, unknown>;
}

const MAX_LOG = 200;

export function useJobEvents(jobId: string, enabled = true) {
  const qc = useQueryClient();
  const [state, setState] = useState<ConnectionState>("connecting");
  const [events, setEvents] = useState<JobEvent[]>([]);
  const failures = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    const ctrl = new AbortController();
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let refetchTimer: ReturnType<typeof setTimeout> | null = null;

    const refreshJob = () => {
      // Coalesce bursts of events into one refetch.
      if (refetchTimer) return;
      refetchTimer = setTimeout(() => {
        refetchTimer = null;
        void qc.invalidateQueries({ queryKey: qk.job(jobId) });
      }, 250);
    };

    const startPolling = () => {
      if (pollTimer) return;
      setState("offline");
      pollTimer = setInterval(() => void qc.invalidateQueries({ queryKey: qk.job(jobId) }), 5000);
    };

    void fetchEventSource(`${config.apiBaseUrl}/api/v1/jobs/${jobId}/events`, {
      signal: ctrl.signal,
      openWhenHidden: true,
      async fetch(input, init) {
        const token = await tokenSource.get();
        return fetch(input, { ...init, headers: { ...(init?.headers ?? {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
      },
      async onopen(res) {
        if (res.ok && res.headers.get("content-type")?.includes("text/event-stream")) {
          failures.current = 0;
          setApiReachable(true);
          setState("live");
          if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
          }
          return;
        }
        if (res.status === 401) await tokenSource.get(true);
        if (res.status === 404 || res.status === 403) throw new Error(`fatal:${res.status}`);
        throw new Error(`SSE open failed: ${res.status}`);
      },
      onmessage(msg) {
        if (!msg.event || msg.event === "heartbeat") return;
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse(msg.data || "{}");
        } catch {
          /* ignore */
        }
        const ev: JobEvent = { id: Number(msg.id) || 0, type: msg.event, at: String(data.at ?? new Date().toISOString()), data };
        setEvents((prev) => (prev.some((p) => p.id === ev.id && ev.id) ? prev : [...prev, ev].slice(-MAX_LOG)));
        refreshJob();
        if (msg.event === "interrupt" || msg.event === "status_changed") {
          void qc.invalidateQueries({ queryKey: qk.review(jobId) });
          void qc.invalidateQueries({ queryKey: qk.publishRequest(jobId) });
          void qc.invalidateQueries({ queryKey: qk.drafts(jobId) });
          void qc.invalidateQueries({ queryKey: qk.factCheck(jobId) });
          void qc.invalidateQueries({ queryKey: qk.result(jobId) });
          void qc.invalidateQueries({ queryKey: ["jobs"] });
          void qc.invalidateQueries({ queryKey: qk.dashboard });
        }
      },
      onclose() {
        // Server closed the stream (deploy, timeout): reconnect via onerror's retry path.
        throw new Error("SSE closed");
      },
      onerror(err) {
        if (err instanceof Error && err.message.startsWith("fatal:")) {
          startPolling();
          throw err; // stop retrying
        }
        failures.current += 1;
        setState("reconnecting");
        if (err instanceof TypeError) setApiReachable(false); // network failure, not an HTTP error
        if (failures.current === 3) {
          logger.info("SSE reconnecting repeatedly; polling as fallback", { jobId });
          startPolling();
        }
        return Math.min(1000 * 2 ** failures.current, 30_000); // backoff (ms)
      },
    }).catch(() => {});

    const onOffline = () => setState("offline");
    window.addEventListener("offline", onOffline);
    return () => {
      ctrl.abort();
      window.removeEventListener("offline", onOffline);
      if (pollTimer) clearInterval(pollTimer);
      if (refetchTimer) clearTimeout(refetchTimer);
    };
  }, [jobId, enabled, qc]);

  return { state, events };
}
