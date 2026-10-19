"use client";

/** Tracks whether the API is reachable, so the UI can say "can't reach the server" instead of
 *  surfacing a pile of failed requests. Updated by the API client and the SSE hook. */
import { useSyncExternalStore } from "react";

let reachable = true;
const listeners = new Set<() => void>();
const onChangeHooks = new Set<(v: boolean) => void>();

export function setApiReachable(v: boolean): void {
  if (v === reachable) return;
  reachable = v;
  listeners.forEach((l) => l());
  onChangeHooks.forEach((h) => h(v));
}

export function onApiReachabilityChange(h: (v: boolean) => void): () => void {
  onChangeHooks.add(h);
  return () => onChangeHooks.delete(h);
}

export function useApiReachable(): boolean {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => reachable,
    () => true,
  );
}
