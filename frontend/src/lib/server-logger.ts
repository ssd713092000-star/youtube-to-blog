/**
 * Server-side (Node runtime) logger for the Next.js server: one JSON object per line on stdout, in the
 * shape Cloud Logging parses (`severity`, `message`), so SSR errors land next to the API's logs.
 */
type Level = "DEBUG" | "INFO" | "WARNING" | "ERROR";

function emit(severity: Level, message: string, fields: Record<string, unknown> = {}): void {
  const line = JSON.stringify({
    severity,
    message,
    service: "tube2dev-web",
    timestamp: new Date().toISOString(),
    ...fields,
  });
  if (severity === "ERROR") process.stderr.write(line + "\n");
  else process.stdout.write(line + "\n");
}

export const serverLogger = {
  debug: (m: string, f?: Record<string, unknown>) => emit("DEBUG", m, f),
  info: (m: string, f?: Record<string, unknown>) => emit("INFO", m, f),
  warn: (m: string, f?: Record<string, unknown>) => emit("WARNING", m, f),
  error: (m: string, f?: Record<string, unknown>) => emit("ERROR", m, f),
};
