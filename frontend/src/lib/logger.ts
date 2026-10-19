/**
 * Browser logger.
 *
 * - Always mirrors to the console in development.
 * - Batches info/warn/error entries and ships them to the backend's /api/v1/client-logs sink
 *   (which re-emits them as structured Cloud Logging entries with source=frontend).
 * - Captures uncaught errors and unhandled promise rejections globally.
 * - Never sends secrets: values whose keys look like keys/tokens are dropped, and API keys / bearer
 *   tokens inside strings are redacted before anything leaves the browser.
 */
import { config } from "@/lib/config";

export type LogLevel = "debug" | "info" | "warn" | "error";
type Context = Record<string, unknown>;

interface Entry {
  level: LogLevel;
  message: string;
  ts: string;
  route?: string;
  session_id: string;
  request_id?: string;
  context?: Context;
  stack?: string;
}

const ORDER: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };
const SHIP_LEVEL: LogLevel = process.env.NODE_ENV === "production" ? "info" : "warn";
const MAX_BUFFER = 100;
const FLUSH_MS = 5000;
const SECRET_RE = /(sk-or-[A-Za-z0-9-]{8,}|Bearer\s+[A-Za-z0-9._-]{20,}|eyJ[A-Za-z0-9._-]{30,})/g;

const isBrowser = typeof window !== "undefined";
const sessionId = isBrowser
  ? (sessionStorage.getItem("t2d_session") ??
    (() => {
      const id = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
      sessionStorage.setItem("t2d_session", id);
      return id;
    })())
  : "server";

let buffer: Entry[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
let backoffMs = FLUSH_MS;
let installed = false;

function scrub(value: unknown, depth = 0): unknown {
  if (depth > 3) return "[truncated]";
  if (typeof value === "string") return value.slice(0, 1000).replace(SECRET_RE, "[redacted]");
  if (Array.isArray(value)) return value.slice(0, 30).map((v) => scrub(v, depth + 1));
  if (value instanceof Error) return { name: value.name, message: scrub(value.message) };
  if (value && typeof value === "object") {
    const out: Context = {};
    for (const [k, v] of Object.entries(value as Context).slice(0, 30)) {
      out[k] = /key|token|secret|password|authorization/i.test(k) ? "[redacted]" : scrub(v, depth + 1);
    }
    return out;
  }
  return value;
}

async function flush(useKeepalive = false): Promise<void> {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  if (!buffer.length || !isBrowser) return;
  const entries = buffer.splice(0, 50);
  try {
    await fetch(`${config.apiBaseUrl}/api/v1/client-logs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries, release: config.release }),
      keepalive: useKeepalive,
    });
    backoffMs = FLUSH_MS;
  } catch {
    // Sink unreachable (usually the API is down): keep the entries (bounded) and back off, so we
    // neither lose the logs that explain the outage nor hammer a dead server.
    buffer = [...entries, ...buffer].slice(-MAX_BUFFER);
    backoffMs = Math.min(backoffMs * 2, 60_000);
  }
  if (buffer.length) schedule();
}

function schedule(): void {
  if (!timer && isBrowser) timer = setTimeout(() => void flush(), backoffMs);
}

function write(level: LogLevel, message: string, context?: Context, err?: unknown): void {
  const e: Entry = {
    level,
    message: String(scrub(message)),
    ts: new Date().toISOString(),
    route: isBrowser ? window.location.pathname : undefined,
    session_id: sessionId,
    request_id: typeof context?.requestId === "string" ? context.requestId : undefined,
    context: context ? (scrub(context) as Context) : undefined,
    stack: err instanceof Error && err.stack ? String(scrub(err.stack)).slice(0, 8000) : undefined,
  };
  if (process.env.NODE_ENV !== "production" || level === "error") {
    const fn = level === "debug" ? console.debug : level === "info" ? console.info : level === "warn" ? console.warn : console.error;
    fn(`[${level}] ${message}`, context ?? "", err ?? "");
  }
  if (!isBrowser || ORDER[level] < ORDER[SHIP_LEVEL]) return;
  buffer.push(e);
  if (buffer.length > MAX_BUFFER) buffer = buffer.slice(-MAX_BUFFER);
  if (level === "error" && backoffMs === FLUSH_MS) void flush();
  else schedule();
}

export const logger = {
  debug: (msg: string, ctx?: Context) => write("debug", msg, ctx),
  info: (msg: string, ctx?: Context) => write("info", msg, ctx),
  warn: (msg: string, ctx?: Context) => write("warn", msg, ctx),
  error: (msg: string, err?: unknown, ctx?: Context) => write("error", msg, ctx, err),
  flush,
};

/** Call once on the client (from <Providers>). */
export function installGlobalErrorLogging(): void {
  if (!isBrowser || installed) return;
  installed = true;
  window.addEventListener("error", (ev) => {
    logger.error(ev.message || "Uncaught error", ev.error, { source: ev.filename, line: ev.lineno, col: ev.colno });
  });
  window.addEventListener("unhandledrejection", (ev) => {
    const reason = ev.reason;
    logger.error(reason instanceof Error ? reason.message : "Unhandled promise rejection", reason);
  });
  // Flush what's left when the tab is hidden or closed.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") void flush(true);
  });
}
