/** Next.js instrumentation hooks: structured logs for server start-up and every server-side request error. */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { serverLogger } = await import("@/lib/server-logger");
    serverLogger.info("tube2dev-web started", { release: process.env.NEXT_PUBLIC_RELEASE ?? "dev" });
  }
}

export async function onRequestError(
  err: unknown,
  request: { path: string; method: string; headers: Record<string, string | string[] | undefined> },
  context: { routerKind: string; routePath: string; routeType: string },
): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  const { serverLogger } = await import("@/lib/server-logger");
  const e = err instanceof Error ? err : new Error(String(err));
  const trace = request.headers["x-cloud-trace-context"];
  serverLogger.error(e.message, {
    stack: e.stack,
    digest: (err as { digest?: string }).digest,
    httpRequest: { requestMethod: request.method, requestUrl: request.path },
    route: context.routePath,
    routeType: context.routeType,
    ...(typeof trace === "string" && process.env.GCP_PROJECT
      ? { "logging.googleapis.com/trace": `projects/${process.env.GCP_PROJECT}/traces/${trace.split("/")[0]}` }
      : {}),
  });
}
