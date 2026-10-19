"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { CharCounter, CopyButton, ErrorState, PageHeader, ScorePill } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, Skeleton, Textarea } from "@/components/ui/primitives";
import { api, call } from "@/lib/api/client";
import { qk, useJob, useResult } from "@/lib/hooks/queries";
import { fmtDuration, fmtMoney, fmtTokens, shortenUrl } from "@/lib/utils";

function SocialCard({ label, value, max, onChange, onRegenerate, regenerating }: { label: string; value: string; max: number; onChange: (v: string) => void; onRegenerate: () => void; regenerating: boolean }) {
  return (
    <Card className="flex flex-col p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">{label}</h3>
        <Button size="sm" variant="ghost" onClick={onRegenerate} loading={regenerating}>
          {!regenerating && <RefreshCw className="h-3.5 w-3.5" />} Regenerate
        </Button>
      </div>
      <Textarea rows={label === "X" ? 4 : 8} value={value} onChange={(e) => onChange(e.target.value)} aria-label={`${label} post`} />
      <div className="mt-2 flex items-center justify-between">
        <CharCounter value={value.length} max={max} />
        <CopyButton text={value} />
      </div>
    </Card>
  );
}

export default function ResultPage() {
  const { id } = useParams<{ id: string }>();
  const job = useJob(id);
  const result = useResult(id, job.data?.status === "completed");
  const qc = useQueryClient();
  const [linkedin, setLinkedin] = useState("");
  const [x, setX] = useState("");

  useEffect(() => {
    if (result.data) {
      setLinkedin(result.data.social.linkedin);
      setX(result.data.social.x);
    }
  }, [result.data]);

  const regen = useMutation({
    mutationFn: () => call(() => api.POST("/api/v1/jobs/{job_id}/social/regenerate", { params: { path: { job_id: id } } })),
    onSuccess: (s) => {
      setLinkedin(s.linkedin);
      setX(s.x);
      void qc.invalidateQueries({ queryKey: qk.result(id) });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  if (job.isError || result.isError) return <ErrorState error={job.error ?? result.error} onRetry={() => void result.refetch()} />;
  if (job.data && job.data.status !== "completed") {
    return <p className="py-16 text-center text-sm text-fg-subtle">This job hasn't finished yet.</p>;
  }
  if (!result.data || !job.data) return <Skeleton className="mx-auto h-96 max-w-3xl" />;

  const r = result.data;
  const draft = r.publish_status !== "published";

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader crumbs={[{ label: "Jobs", href: "/dashboard" }, { label: job.data.video_title || job.data.short_id, href: `/jobs/${id}` }, { label: "Result" }]} />

      <Card className="animate-rise p-6">
        <div className="flex items-start gap-4">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-success-bg text-success" aria-hidden>
            ✓
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-semibold">{r.title}</h1>
              <span className={draft ? "rounded bg-sidebar px-2 py-0.5 text-xs text-fg-muted" : "rounded bg-success-bg px-2 py-0.5 text-xs text-success"}>
                {draft ? "Draft" : "Public"}
              </span>
            </div>
            {r.devto_url && <p className="mt-1 truncate font-mono text-xs text-fg-subtle">{shortenUrl(r.devto_url)}</p>}
            {draft && <p className="mt-2 text-sm text-fg-subtle">Saved as a private draft. Publish it from your dev.to dashboard when ready.</p>}
          </div>
          {r.devto_url && (
            <a href={r.devto_url} target="_blank" rel="noreferrer">
              <Button variant="primary">
                Open on dev.to <ExternalLink className="h-3.5 w-3.5" />
              </Button>
            </a>
          )}
        </div>
        <dl className="mt-6 grid grid-cols-2 gap-3 border-t border-border pt-5 text-sm sm:grid-cols-5">
          {[
            ["Total time", fmtDuration(r.summary.total_seconds)],
            ["Cost", fmtMoney(r.summary.cost_usd, true)],
            ["Tokens", fmtTokens(r.summary.tokens)],
            ["Revisions", String(r.summary.revisions)],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-xs text-fg-subtle">{k}</dt>
              <dd className="mt-0.5 font-mono font-medium">{v}</dd>
            </div>
          ))}
          <div>
            <dt className="text-xs text-fg-subtle">Faithfulness</dt>
            <dd className="mt-0.5">
              <ScorePill score={r.summary.faithfulness_score} />
            </dd>
          </div>
        </dl>
      </Card>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <SocialCard label="LinkedIn" value={linkedin} max={3000} onChange={setLinkedin} onRegenerate={() => regen.mutate()} regenerating={regen.isPending} />
        <SocialCard label="X" value={x} max={280} onChange={setX} onRegenerate={() => regen.mutate()} regenerating={regen.isPending} />
      </div>
    </div>
  );
}
