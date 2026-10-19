import { clsx, type ClassValue } from "clsx";
import { formatDistanceToNowStrict } from "date-fns";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** 372 -> "06:12", 3725 -> "1:02:05" */
export function fmtTimestamp(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = String(m).padStart(h ? 2 : 2, "0");
  const ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m < 60 ? `${m}m ${s}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function fmtMoney(usd: number | null | undefined, precise = false): string {
  if (usd == null) return "—";
  if (usd === 0) return "$0.00";
  if (usd < 0.01) return precise ? `$${usd.toFixed(4)}` : "<$0.01";
  return `$${usd.toFixed(2)}`;
}

export function fmtTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}k` : String(n);
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Date.now() - d.getTime() < 45_000) return "just now";
  return `${formatDistanceToNowStrict(d)} ago`;
}

export function shortenUrl(url: string): string {
  return url.replace(/^https?:\/\/(www\.)?/, "");
}
