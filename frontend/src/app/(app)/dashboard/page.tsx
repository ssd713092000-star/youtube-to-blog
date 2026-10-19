"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { EmptyState, ErrorState, Money, PageHeader, ScorePill, StatusBadge } from "@/components/common";
import { NewPostButton, ThemeToggle } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Card, Input, Skeleton } from "@/components/ui/primitives";
import type { Schemas } from "@/lib/api/client";
import { ACTIVE_STATUSES, useDashboard, useJobs } from "@/lib/hooks/queries";
import { jobHref } from "@/lib/routes";
import { cn, fmtMoney, fmtRelative } from "@/lib/utils";

type Job = Schemas["JobSummary"];
const TABS = [
  ["all", "All"],
  ["in_progress", "In progress"],
  ["needs_you", "Needs you"],
  ["completed", "Completed"],
  ["failed", "Failed"],
] as const;

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Card className="px-4 py-3">
      <div className="text-xs text-fg-subtle">{label}</div>
      <div className="mt-1 text-xl font-semibold tracking-tight">{children}</div>
    </Card>
  );
}

function Thumb({ src, className }: { src: string; className?: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src || "/placeholder.svg"} alt="" loading="lazy" className={cn("aspect-video rounded object-cover bg-sidebar", className)} />
  );
}

function AttentionCard({ job }: { job: Job }) {
  const label =
    job.pending_action === "draft_review" ? "Review draft →" : job.pending_action === "publish_approval" ? "Approve publish →" : "Retry failed step →";
  return (
    <Link href={jobHref(job)} className="group flex gap-3 rounded-[10px] border border-border bg-surface p-3 hover:border-accent/50">
      <Thumb src={job.thumbnail_url} className="w-24 shrink-0" />
      <div className="min-w-0">
        <div className="truncate text-sm font-medium">{job.video_title || job.video_id}</div>
        <div className="mt-1 text-sm font-medium text-accent group-hover:underline">{label}</div>
        <div className="mt-0.5 text-xs text-fg-subtle">
          {job.status === "failed" ? fmtRelative(job.updated_at) : `${fmtRelative(job.updated_at).replace(" ago", "")} waiting`}
        </div>
      </div>
    </Link>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("all");
  const [q, setQ] = useState("");
  const [url, setUrl] = useState("");
  const dash = useDashboard();
  const jobs = useJobs(tab, q);
  const attention = useJobs("needs_you", "");
  const failed = useJobs("failed", "");

  const rows = jobs.data?.pages.flatMap((p) => p.items) ?? [];
  const counts = jobs.data?.pages[0]?.counts;
  const needs = [
    ...(attention.data?.pages[0]?.items ?? []),
    ...(failed.data?.pages[0]?.items ?? []).filter((j) => j.rejection_code == null).slice(0, 2),
  ].slice(0, 6);

  return (
    <>
      <PageHeader title="Dashboard" actions={<><ThemeToggle /><NewPostButton /></>} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Posts this month">{dash.data ? dash.data.posts_this_month : <Skeleton className="h-6 w-10" />}</Stat>
        <Stat label="Avg. faithfulness">
          {dash.data ? <span className="font-mono">{dash.data.avg_faithfulness?.toFixed(2) ?? "—"}</span> : <Skeleton className="h-6 w-12" />}
        </Stat>
        <Stat label="Spend this month">
          {dash.data ? (
            <>
              <Money usd={dash.data.spend_this_month} />
              <span className="ml-1 text-sm font-normal text-fg-subtle">/ {fmtMoney(dash.data.monthly_budget_usd)}</span>
            </>
          ) : (
            <Skeleton className="h-6 w-20" />
          )}
        </Stat>
        <Stat label="Awaiting you">{dash.data ? dash.data.awaiting_you : <Skeleton className="h-6 w-8" />}</Stat>
      </div>

      {needs.length > 0 && (
        <section className="mt-8" aria-labelledby="attention">
          <h2 id="attention" className="mb-3 text-sm font-semibold">
            Needs your attention
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {needs.map((j) => (
              <AttentionCard key={j.id} job={j} />
            ))}
          </div>
        </section>
      )}

      <section className="mt-8">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <div role="tablist" aria-label="Filter jobs" className="flex gap-1 rounded-lg bg-sidebar p-1">
            {TABS.map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-medium",
                  tab === key ? "bg-surface text-fg shadow-sm" : "text-fg-subtle hover:text-fg",
                )}
              >
                {label}
                {counts && <span className="ml-1.5 font-mono text-fg-faint">{counts[key]}</span>}
              </button>
            ))}
          </div>
          <div className="relative ml-auto w-full max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-fg-faint" />
            <Input className="pl-8" placeholder="Search titles or channels…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search jobs" />
          </div>
        </div>

        {jobs.isError ? (
          <ErrorState error={jobs.error} onRetry={() => void jobs.refetch()} />
        ) : jobs.isLoading ? (
          <Card className="space-y-3 p-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </Card>
        ) : rows.length === 0 && !q && tab === "all" ? (
          <EmptyState
            title="Paste a YouTube link to write your first post"
            body="We'll fetch the transcript, write a draft and fact-check it. You approve everything before it's published."
            action={
              <form
                className="flex w-full max-w-md gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  router.push(`/jobs/new?url=${encodeURIComponent(url)}`);
                }}
              >
                <Input placeholder="https://youtu.be/…" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="YouTube URL" />
                <Button variant="primary" type="submit">
                  Start
                </Button>
              </form>
            }
          />
        ) : rows.length === 0 ? (
          <EmptyState title="No jobs match" body="Try another filter or search." />
        ) : (
          <Card className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-fg-subtle">
                  <th className="px-4 py-2.5 font-medium">Video</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="px-3 py-2.5 font-medium">Faithful.</th>
                  <th className="px-3 py-2.5 font-medium">Revs</th>
                  <th className="px-3 py-2.5 font-medium">Cost</th>
                  <th className="px-3 py-2.5 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((j) => {
                  const live = ACTIVE_STATUSES.has(j.status);
                  return (
                    <tr
                      key={j.id}
                      onClick={() => router.push(jobHref(j))}
                      className="relative cursor-pointer overflow-hidden border-b border-border last:border-0 hover:bg-sidebar/60"
                    >
                      <td className="relative px-4 py-2.5">
                        {live && (
                          <span aria-hidden className="pointer-events-none absolute inset-y-0 left-0 w-1/3 animate-shimmer bg-gradient-to-r from-transparent via-accent/10 to-transparent" />
                        )}
                        <Link href={jobHref(j)} className="flex items-center gap-3" onClick={(e) => e.stopPropagation()}>
                          <Thumb src={j.thumbnail_url} className="w-16 shrink-0" />
                          <span className="min-w-0">
                            <span className="block truncate font-medium">{j.video_title || j.video_id}</span>
                            <span className="block truncate text-xs text-fg-subtle">{j.channel_name}</span>
                          </span>
                        </Link>
                      </td>
                      <td className="px-3 py-2.5">
                        <StatusBadge status={j.status} detail={j.progress_label} />
                      </td>
                      <td className="px-3 py-2.5">
                        <ScorePill score={j.faithfulness_score} />
                      </td>
                      <td className="px-3 py-2.5 font-mono text-xs">{j.revision_count}</td>
                      <td className="px-3 py-2.5">
                        <Money usd={j.cost_usd} className="text-xs" />
                      </td>
                      <td className="px-3 py-2.5 text-xs text-fg-subtle">{fmtRelative(j.updated_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {jobs.hasNextPage && (
              <div className="border-t border-border p-3 text-center">
                <Button size="sm" loading={jobs.isFetchingNextPage} onClick={() => void jobs.fetchNextPage()}>
                  Load more
                </Button>
              </div>
            )}
          </Card>
        )}
      </section>
    </>
  );
}
