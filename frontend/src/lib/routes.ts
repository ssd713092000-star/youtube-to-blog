import type { Schemas } from "@/lib/api/client";

type JobLike = Pick<Schemas["JobSummary"], "id" | "pending_action" | "status">;

/** Where a job's row/card should take the user, based on what it's waiting for. */
export function jobHref(j: JobLike): string {
  if (j.pending_action === "draft_review") return `/jobs/${j.id}/review`;
  if (j.pending_action === "publish_approval") return `/jobs/${j.id}/publish`;
  if (j.status === "completed") return `/jobs/${j.id}/result`;
  return `/jobs/${j.id}`;
}
