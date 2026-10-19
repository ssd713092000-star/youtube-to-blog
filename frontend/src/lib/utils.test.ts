import { describe, expect, it } from "vitest";

import { cleanTag } from "@/components/review/Quality";
import { jobHref } from "@/lib/routes";
import { fmtMoney, fmtTimestamp } from "@/lib/utils";

describe("format helpers", () => {
  it("formats timestamps like the mockups", () => {
    expect(fmtTimestamp(372)).toBe("06:12");
    expect(fmtTimestamp(3725)).toBe("1:02:05");
  });
  it("formats money", () => {
    expect(fmtMoney(0)).toBe("$0.00");
    expect(fmtMoney(0.004)).toBe("<$0.01");
    expect(fmtMoney(0.004, true)).toBe("$0.0040");
    expect(fmtMoney(1.84)).toBe("$1.84");
  });
});

describe("tags", () => {
  it("lowercases and strips to letters and digits like dev.to", () => {
    expect(cleanTag("Rust!")).toBe("rust");
    expect(cleanTag("Next.js 15")).toBe("nextjs15");
  });
});

describe("jobHref", () => {
  it("routes to whatever the job is waiting for", () => {
    expect(jobHref({ id: "a", pending_action: "draft_review", status: "awaiting_review" })).toBe("/jobs/a/review");
    expect(jobHref({ id: "a", pending_action: "publish_approval", status: "awaiting_publish" })).toBe("/jobs/a/publish");
    expect(jobHref({ id: "a", pending_action: null, status: "completed" })).toBe("/jobs/a/result");
    expect(jobHref({ id: "a", pending_action: null, status: "running" })).toBe("/jobs/a");
  });
});
