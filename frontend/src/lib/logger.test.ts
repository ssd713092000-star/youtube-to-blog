import { afterEach, describe, expect, it, vi } from "vitest";

import { logger } from "@/lib/logger";

describe("logger", () => {
  afterEach(() => vi.restoreAllMocks());

  it("ships errors immediately and redacts secrets before they leave the browser", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "error").mockImplementation(() => {});

    logger.error("save failed for sk-or-v1-abcdefghijklmnop", new Error("boom"), { api_key: "secret", jobId: "j1" });
    await logger.flush();

    expect(fetchMock).toHaveBeenCalled();
    const body = JSON.parse(fetchMock.mock.calls[0]![1].body as string);
    const entry = body.entries[0];
    expect(entry.level).toBe("error");
    expect(entry.message).not.toContain("sk-or-v1");
    expect(entry.context.api_key).toBe("[redacted]");
    expect(entry.context.jobId).toBe("j1");
    expect(entry.stack).toContain("boom");
  });

  it("never throws when the log sink is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
    vi.spyOn(console, "error").mockImplementation(() => {});
    logger.error("x");
    await expect(logger.flush()).resolves.toBeUndefined();
  });
});
