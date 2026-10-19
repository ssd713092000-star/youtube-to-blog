"use client";

import { MoreHorizontal, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog, ConnectionIndicator, ErrorState, PageHeader, ScorePill, StatusBadge } from "@/components/common";
import { ActivityLog, PipelineStepper, UsageMeter } from "@/components/jobs/Pipeline";
import { Button } from "@/components/ui/button";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownSeparator, DropdownTrigger } from "@/components/ui/overlay";
import { Card, Input, Label, SectionTitle, Skeleton } from "@/components/ui/primitives";
import { api, call, type Schemas } from "@/lib/api/client";
import { useDrafts, useFactCheck, useJob } from "@/lib/hooks/queries";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { useResumeAction } from "@/lib/hooks/useResumeAction";
import { fmtRelative, fmtTimestamp, shortenUrl } from "@/lib/utils";

type Job = Schemas["JobDetail"];

function PausedBanner({ job }: { job: Job }) {
  if (!job.pending_action) return null;
  const review = job.pending_action === "draft_review";
  return (
    <div className="sticky top-0 z-10 mb-5 flex flex-wrap items-center gap-3 rounded-[10px] border border-warning/30 bg-warning-bg px-4 py-3 text-sm text-warning-strong" role="status">
      <span aria-hidden>❚❚</span>
      <span className="font-medium">{review ? "Your draft is ready for review." : "Approve the dev.to publish."}</span>
      <Link href={`/jobs/${job.id}/${review ? "review" : "publish"}`} className="ml-auto">
        <Button variant="primary" size="sm">
          {review ? "Review draft →" : "Approve publish →"}
        </Button>
      </Link>
    </div>
  );
}

const STALL_MS = 120_000;

/** Warn when the running step has had no LLM response for a while (slow/overloaded model, provider outage). */
function StallHint({ job, lastUsageAt }: { job: Job; lastUsageAt: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 10_000);
    return () => clearInterval(t);
  }, []);
  if (job.status !== "running") return null;
  const step = job.steps.find((s) => s.state === "running");
  if (!step?.started_at || step.step === "human_review" || step.step === "publish") return null;
  const since = Math.max(new Date(step.started_at).getTime(), lastUsageAt ? new Date(lastUsageAt).getTime() : 0);
  if (now - since < STALL_MS) return null;
  return (
    <div className="mb-5 rounded-[10px] border border-warning/30 bg-warning-bg/60 px-4 py-3 text-sm text-warning-strong" role="status">
      No response from <span className="font-mono">{job.config.model}</span> for {Math.round((now - since) / 60_000)} min. Slow or
      overloaded models can take a while and failed calls are retried automatically. You can also cancel and start again with a
      faster model.
    </div>
  );
}

function ErrorsPanel({ job }: { job: Job }) {
  const last = job.errors[job.errors.length - 1];
  const budgetHit = last?.code === "budget_exceeded";
  const [budget, setBudget] = useState(() => Math.ceil(job.budget_usd * 2 * 100) / 100);
  const retry = useResumeAction(job.id, (args: { budget?: number }, key) =>
    call(() =>
      api.POST("/api/v1/jobs/{job_id}/retry", {
        params: { path: { job_id: job.id }, header: { "idempotency-key": key } },
        body: args.budget ? { budget_usd: args.budget } : {},
      }),
    ),
  { label: "retry" });
  if (job.status !== "failed" || !last) return null;
  return (
    <Card className="mb-5 border-danger/30 p-4" role="alert">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-danger">
            {budgetHit ? "Job budget reached (402)" : `Failed at ${last.step ?? "a step"}`}
          </p>
          <p className="mt-1 break-words text-sm text-fg-muted">{last.message}</p>
          <p className="mt-1 font-mono text-[11px] text-fg-subtle">
            {last.code} · {fmtRelative(last.at)}
          </p>
        </div>
        <Button size="sm" variant="ghost" onClick={() => void navigator.clipboard.writeText(JSON.stringify(last, null, 2)).then(() => toast.success("Error details copied"))}>
          Copy error details
        </Button>
      </div>
      {last.retryable ? (
        <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-border pt-4">
          {budgetHit && (
            <div>
              <Label htmlFor="newbudget">New budget</Label>
              <Input id="newbudget" type="number" step={0.05} min={job.budget_usd} value={budget} onChange={(e) => setBudget(Number(e.target.value))} className="w-28 font-mono" />
            </div>
          )}
          <Button variant="primary" loading={retry.pending} onClick={() => void retry.run(budgetHit ? { budget } : {})}>
            <RefreshCw className="h-3.5 w-3.5" /> {budgetHit ? "Raise budget & retry" : "Retry from last checkpoint"}
          </Button>
          <p className="text-xs text-fg-subtle">Completed steps won't re-run or be billed again.</p>
        </div>
      ) : (
        <p className="mt-3 text-xs text-fg-subtle">Retrying won't fix this one. Start a new post instead.</p>
      )}
    </Card>
  );
}

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const job = useJob(id);
  const { state, events } = useJobEvents(id, !!job.data && !["completed", "rejected", "cancelled"].includes(job.data.status));
  const drafts = useDrafts(id, !!job.data?.current_draft_rev);
  const fc = useFactCheck(id, job.data?.faithfulness_score != null);
  const [confirm, setConfirm] = useState<"cancel" | "delete" | null>(null);

  const cancel = useResumeAction(id, (_: object, key) =>
    call(() => api.POST("/api/v1/jobs/{job_id}/cancel", { params: { path: { job_id: id }, header: { "idempotency-key": key } } })),
  { label: "cancel", onSuccess: () => setConfirm(null) });
  const [deleting, setDeleting] = useState(false);

  if (job.isError) return <ErrorState error={job.error} onRetry={() => void job.refetch()} />;
  if (!job.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-80" />
        <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
          <Skeleton className="h-[520px]" />
          <Skeleton className="h-[320px]" />
        </div>
      </div>
    );
  }
  const j = job.data;
  const active = ["queued", "running", "publishing", "awaiting_review", "awaiting_publish"].includes(j.status);

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Jobs", href: "/dashboard" }, { label: j.short_id }]}
        actions={
          <>
            {active && <ConnectionIndicator state={state} />}
            <DropdownMenu>
              <DropdownTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="Job actions">
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownTrigger>
              <DropdownContent>
                <DropdownItem onSelect={() => void navigator.clipboard.writeText(j.id).then(() => toast.success("Job ID copied"))}>Copy job ID</DropdownItem>
                {j.status === "completed" && <DropdownItem onSelect={() => router.push(`/jobs/${id}/result`)}>View result</DropdownItem>}
                <DropdownSeparator />
                <DropdownItem danger disabled={!active} onSelect={() => setConfirm("cancel")}>
                  Cancel job
                </DropdownItem>
                <DropdownItem danger disabled={["queued", "running", "publishing"].includes(j.status)} onSelect={() => setConfirm("delete")}>
                  Delete
                </DropdownItem>
              </DropdownContent>
            </DropdownMenu>
          </>
        }
      />

      <div className="mb-6 flex flex-wrap items-center gap-4">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={j.thumbnail_url || "/placeholder.svg"} alt="" className="aspect-video w-28 rounded object-cover" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-xl font-semibold tracking-tight">{j.video_title || j.video_id}</h1>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-sm text-fg-subtle">
            {j.channel_name}
            <span>·</span>
            <a href={j.video_url} target="_blank" rel="noreferrer" className="font-mono text-xs hover:text-accent">
              {shortenUrl(j.video_url).slice(0, 30)}…
            </a>
            {j.duration_seconds > 0 && (
              <>
                <span>·</span>
                <span className="font-mono text-xs">{fmtTimestamp(j.duration_seconds)}</span>
              </>
            )}
          </p>
        </div>
        <StatusBadge status={j.status} detail={j.progress_label} />
      </div>

      <PausedBanner job={j} />
      <StallHint job={j} lastUsageAt={[...events].reverse().find((e) => e.type === "usage")?.at ?? null} />
      <ErrorsPanel job={j} />
      {j.status === "rejected" && j.rejection_reason && (
        <Card className="mb-5 p-4 text-sm" role="status">
          <p className="font-medium">⊘ {j.rejection_reason}</p>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-5">
          <Card className="p-5">
            <PipelineStepper job={j} />
          </Card>
          <ActivityLog events={events} />
        </div>

        <aside className="space-y-5">
          <Card className="p-4">
            <SectionTitle>Usage</SectionTitle>
            <UsageMeter job={j} />
          </Card>
          <Card className="p-4">
            <SectionTitle>Run config</SectionTitle>
            <dl className="grid grid-cols-[1fr_auto] gap-y-1.5 text-sm">
              <dt className="text-fg-subtle">Model</dt>
              <dd className="truncate font-mono text-xs">{j.config.model.split("/").pop()}</dd>
              <dt className="text-fg-subtle">Min. faithfulness</dt>
              <dd className="font-mono text-xs">{j.config.min_faithfulness.toFixed(2)}</dd>
              <dt className="text-fg-subtle">Max revisions</dt>
              <dd className="font-mono text-xs">{j.config.max_revisions}</dd>
              <dt className="text-fg-subtle">Attribution</dt>
              <dd className="text-xs">{j.config.attribution_mode === "credited" ? "Credited" : "My video"}</dd>
            </dl>
          </Card>
          <Card className="p-4">
            <SectionTitle>Draft versions</SectionTitle>
            {!drafts.data?.length ? (
              <p className="text-sm text-fg-subtle">Appear after the post is assembled.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {drafts.data.map((d) => (
                  <li key={d.rev} className="flex items-center justify-between">
                    <span>
                      <span className="font-mono text-xs">rev {d.rev}</span> <span className="text-fg-subtle">· {d.kind.replace("_", " ")}</span>
                    </span>
                    <span className="text-xs text-fg-faint">{fmtRelative(d.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card className="p-4">
            <SectionTitle>Fact-check</SectionTitle>
            {!fc.data ? (
              <p className="text-sm text-fg-subtle">Pending.</p>
            ) : (
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-fg-subtle">Faithfulness</span>
                  <ScorePill score={fc.data.faithfulness_score} min={fc.data.min_faithfulness} />
                </div>
                <div className="flex justify-between">
                  <span className="text-fg-subtle">Claims</span>
                  <span className="font-mono text-xs">
                    {fc.data.claims.filter((c) => !c.supported).length} of {fc.data.claims.length} ⚠
                  </span>
                </div>
              </div>
            )}
          </Card>
        </aside>
      </div>

      <ConfirmDialog
        open={confirm === "cancel"}
        onOpenChange={(v) => !v && setConfirm(null)}
        title="Cancel this job?"
        body="The pipeline stops after the current step. Nothing will be published. You can't resume a cancelled job."
        confirmLabel="Cancel job"
        danger
        loading={cancel.pending}
        onConfirm={() => void cancel.run({})}
      />
      <ConfirmDialog
        open={confirm === "delete"}
        onOpenChange={(v) => !v && setConfirm(null)}
        title="Delete this job?"
        body="This deletes the job, its drafts and its pipeline history. Published dev.to articles are not affected."
        confirmLabel="Delete"
        danger
        loading={deleting}
        onConfirm={async () => {
          setDeleting(true);
          try {
            await call(() => api.DELETE("/api/v1/jobs/{job_id}", { params: { path: { job_id: id } } }));
            toast.success("Job deleted");
            router.replace("/dashboard");
          } catch (e) {
            toast.error((e as Error).message);
          } finally {
            setDeleting(false);
          }
        }}
      />
    </>
  );
}
