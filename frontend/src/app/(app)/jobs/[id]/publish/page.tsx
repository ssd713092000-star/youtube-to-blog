"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { ErrorState, PageHeader } from "@/components/common";
import { MarkdownPreview } from "@/components/review/Markdown";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/overlay";
import { Card, Input, Skeleton, Textarea } from "@/components/ui/primitives";
import { api, call } from "@/lib/api/client";
import { useDraft, useJob, usePublishRequest } from "@/lib/hooks/queries";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { useResumeAction } from "@/lib/hooks/useResumeAction";
import { cn } from "@/lib/utils";

type Decision = { decision: "approve" | "reject"; published: boolean; message?: string; checkpoint: string };

export default function PublishPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const job = useJob(id);
  useJobEvents(id);
  const pr = usePublishRequest(id, job.data?.pending_action === "publish_approval");
  const final = useDraft(id, pr.data?.final_rev);
  const [visibility, setVisibility] = useState<"draft" | "public">("draft");
  const [typed, setTyped] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  const submit = useResumeAction(
    id,
    (d: Decision, key) =>
      call(() =>
        api.POST("/api/v1/jobs/{job_id}/publish", {
          params: { path: { job_id: id }, header: { "idempotency-key": key } },
          body: { decision: d.decision, published: d.published, message: d.message ?? null, expected_checkpoint_id: d.checkpoint },
        }),
      ),
    { label: "publish", onSuccess: () => router.push(`/jobs/${id}`) },
  );

  if (job.data && job.data.pending_action !== "publish_approval" && !submit.pending) {
    return (
      <div className="mx-auto max-w-lg py-16 text-center">
        <p className="text-sm text-fg-subtle">This job isn't waiting for publish approval.</p>
        <Button className="mt-4" onClick={() => router.push(job.data?.status === "completed" ? `/jobs/${id}/result` : `/jobs/${id}`)}>
          Back to the job
        </Button>
      </div>
    );
  }
  if (pr.isError) return <ErrorState error={pr.error} onRetry={() => void pr.refetch()} />;
  if (!job.data || !pr.data) return <Skeleton className="mx-auto h-[520px] max-w-2xl" />;

  const p = pr.data;
  const isPublic = visibility === "public";
  const canApprove = !isPublic || typed.trim().toLowerCase() === "publish";
  const checkpoint = job.data.checkpoint_id ?? "";
  const handle = p.devto_username ? `@${p.devto_username}` : "your dev.to account";

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader crumbs={[{ label: "Jobs", href: "/dashboard" }, { label: job.data.video_title || job.data.short_id, href: `/jobs/${id}` }, { label: "Publish" }]} />
      <div className="mb-5 flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Approve the dev.to publish</h1>
        <span className="text-sm text-fg-subtle">
          Publishing to <span className="font-mono text-fg">{handle}</span>
        </span>
      </div>

      <Card className="divide-y divide-border">
        <div className="flex items-center justify-between px-4 py-2.5">
          <span className="text-xs font-semibold uppercase tracking-wide text-fg-subtle">Summary</span>
          <Dialog>
            <DialogTrigger className="text-sm text-accent hover:underline">View final draft →</DialogTrigger>
            <DialogContent title={p.title} side="right">
              {final.data ? <MarkdownPreview markdown={final.data.markdown} /> : <Skeleton className="h-96" />}
            </DialogContent>
          </Dialog>
        </div>
        <dl className="grid grid-cols-[110px_1fr] gap-y-3 px-4 py-4 text-sm">
          <dt className="text-fg-subtle">Title</dt>
          <dd className="font-medium">{p.title}</dd>
          <dt className="text-fg-subtle">Tags</dt>
          <dd className="flex flex-wrap gap-1.5">
            {p.tags.map((t) => (
              <span key={t} className="rounded bg-sidebar px-2 py-0.5 font-mono text-xs">
                #{t}
              </span>
            ))}
          </dd>
          <dt className="text-fg-subtle">Description</dt>
          <dd>{p.description}</dd>
          <dt className="text-fg-subtle">Body</dt>
          <dd className="font-mono text-xs">
            {p.body_char_count.toLocaleString()} chars · rev {p.final_rev} final
          </dd>
          <dt className="text-fg-subtle">Attribution</dt>
          <dd>{p.attribution_mode === "credited" ? <>Credit block for <span className="font-medium">{p.channel_name}</span> + video embed</> : "Your video + embed"}</dd>
          {p.canonical_url && (
            <>
              <dt className="text-fg-subtle">Canonical</dt>
              <dd className="truncate font-mono text-xs">{p.canonical_url}</dd>
            </>
          )}
        </dl>
      </Card>

      <div className="mt-5 grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Visibility">
        {(
          [
            ["draft", "Save as private draft", "Lands in your dev.to dashboard. Publish it there when ready.", true],
            ["public", "Publish publicly now", "Visible to everyone and in the dev.to feed immediately.", false],
          ] as const
        ).map(([k, t, d, rec]) => (
          <button
            key={k}
            role="radio"
            aria-checked={visibility === k}
            onClick={() => {
              setVisibility(k);
              setTyped("");
            }}
            className={cn(
              "rounded-[10px] border p-4 text-left transition-colors",
              visibility === k ? (k === "public" ? "border-warning bg-warning-bg/40" : "border-accent bg-accent-tint/40") : "border-border bg-surface hover:border-border-strong",
            )}
          >
            <span className="flex items-center gap-2 text-sm font-medium">
              <span className={cn("h-3.5 w-3.5 rounded-full border-2", visibility === k ? "border-accent bg-accent" : "border-border-strong")} />
              {t}
              {rec && <span className="rounded bg-sidebar px-1.5 py-px text-[11px] font-normal text-fg-subtle">recommended</span>}
            </span>
            <span className="mt-1.5 block pl-5.5 text-xs text-fg-subtle">{d}</span>
          </button>
        ))}
      </div>

      {isPublic && (
        <div className="mt-3 animate-rise rounded-lg border border-warning/40 bg-warning-bg/50 p-3 text-sm">
          This post goes live on <span className="font-mono font-medium">{handle}</span>. Type <span className="font-mono font-semibold">publish</span> to confirm.
          <Input className="mt-2 font-mono" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="publish" aria-label="Type publish to confirm" autoFocus />
        </div>
      )}

      {rejecting && (
        <div className="mt-4 animate-rise">
          <Textarea rows={3} placeholder="Why not? (optional)" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reject reason" />
        </div>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-border pt-5">
        {rejecting ? (
          <>
            <Button variant="ghost" onClick={() => setRejecting(false)}>
              Back
            </Button>
            <Button variant="danger" loading={submit.pending} onClick={() => void submit.run({ decision: "reject", published: false, message: reason || undefined, checkpoint })}>
              Reject publish
            </Button>
          </>
        ) : (
          <Button variant="ghost" onClick={() => setRejecting(true)}>
            Reject…
          </Button>
        )}
        <span className="ml-auto text-xs text-fg-subtle">Retries are safe — no duplicates.</span>
        {!rejecting && (
          <Button
            variant="primary"
            size="lg"
            disabled={!canApprove}
            loading={submit.pending}
            onClick={() => void submit.run({ decision: "approve", published: isPublic, checkpoint })}
          >
            {submit.pending ? "Sending to dev.to…" : isPublic ? "Approve & publish" : "Approve & save draft"}
          </Button>
        )}
      </div>
    </div>
  );
}
