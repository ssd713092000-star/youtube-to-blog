/**
 * Typed API client generated from the backend's OpenAPI spec (`npm run gen:api`).
 * Adds the Firebase ID token, refreshes it once on 401, logs failures with the backend request id,
 * and turns the error envelope {error:{code,message,details}} into ApiError.
 */
import createClient, { type Middleware } from "openapi-fetch";

import { setApiReachable } from "@/lib/api/health";
import { tokenSource } from "@/lib/auth";
import { config } from "@/lib/config";
import { logger } from "@/lib/logger";
import type { components, paths } from "@/lib/api/schema";

export type Schemas = components["schemas"];

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
    public requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    const fields = (this.details.fields as { field: string; message: string }[] | undefined) ?? [];
    for (const f of fields) out[f.field] = f.message;
    if (typeof this.details.field === "string") out[this.details.field] = this.message;
    return out;
  }
  get retryAfter(): number | null {
    const v = this.details.retry_after;
    return typeof v === "number" ? v : null;
  }
}

const auth: Middleware = {
  async onRequest({ request }) {
    const token = await tokenSource.get();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: config.apiBaseUrl });
api.use(auth);

async function toError(res: Response): Promise<ApiError> {
  const requestId = res.headers.get("x-request-id");
  let body: { error?: { code?: string; message?: string; details?: Record<string, unknown> } } = {};
  try {
    body = await res.clone().json();
  } catch {
    /* non-JSON error */
  }
  const e = body.error ?? {};
  const err = new ApiError(res.status, e.code ?? "http_error", e.message ?? res.statusText, e.details ?? {}, requestId);
  if (res.status >= 500) logger.error(`API ${res.status} ${res.url}`, err, { requestId, code: err.code });
  else if (res.status !== 401 && res.status !== 404 && res.status !== 409) logger.warn(`API ${res.status}`, { url: res.url, code: err.code, requestId });
  return err;
}

/**
 * Unwrap an openapi-fetch call: returns data or throws ApiError. Retries once with a refreshed token on 401.
 * Usage: `const job = await call(() => api.GET("/api/v1/jobs/{job_id}", { params: { path: { job_id } } }))`
 */
async function attempt<T>(fn: () => Promise<{ data?: T; error?: unknown; response: Response }>) {
  try {
    const r = await fn();
    setApiReachable(true);
    return r;
  } catch (e) {
    // fetch() rejects only on network failure (server down, DNS, CORS): not an app error.
    setApiReachable(false);
    throw new ApiError(0, "network_error", "Can't reach the server.", { cause: String(e) });
  }
}

export async function call<T>(fn: () => Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let r = await attempt(fn);
  if (r.response.status === 401) {
    await tokenSource.get(true); // force-refresh the cached ID token, then retry once
    r = await attempt(fn);
    if (r.response.status === 401) tokenSource.onUnauthorized();
  }
  if (!r.response.ok) throw await toError(r.response);
  return r.data as T;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
