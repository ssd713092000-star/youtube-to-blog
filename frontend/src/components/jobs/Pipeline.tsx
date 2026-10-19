"use client";

import { ChevronDown, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Tooltip } from "@/components/ui/overlay";
import type { Schemas } from "@/lib/api/client";
import type { JobEvent } from "@/lib/hooks/useJobEvents";
import { cn, fmtDuration, fmtMoney, fmtTokens } from "@/lib/utils";

type Step = Schemas["StepOut"];
type Job = Schemas["JobDetail"];

function elapsed(s: Step, now: number): number | null {
  if (!s.started_at) return null;
  const end = s.finished_at ? new Date(s.finished_at).getTime() : s.state === "running" ? now : null;
  return end ? (end - new Date(s.started_at).getTime()) / 1000 : null;
}

function Glyph({ state }: { state: Step["state"] }) {
  const base = "grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[11px] font-semibold";
  switch (state) {
    case "done":
      return <span className={cn(base, "border-success/30 bg-success-bg text-success")}>✓</span>;
    case "running":
      return (
        <span className={cn(base, "animate-pulse-node border-accent bg-accent-tint text-accent")}>
          <Loader2 className="h-3 w-3 animate-spin" />
        </span>
      );
    case "waiting":
      return <span className={cn(base, "border-warning/40 bg-warning-bg text-warning-strong")}>❚❚</span>;
    case "failed":
      return <span className={cn(base, "border-danger/30 bg-danger-bg text-danger")}>✕</span>;
    case "skipped":
      return <span className={cn(base, "border-dashed border-border text-fg-faint")}>–</span>;
    default:
      return <span className={cn(base, "border-border text-fg-faint")}>○</span>;
  }
}

const SUB_GLYPH: Record<string, string> = { done: "✓", running: "◌", pending: "○", failed: "✕" };

function Node({ step, label, extra, now, last }: { step: Step; label: React.ReactNode; extra?: React.ReactNode; now: number; last?: boolean }) {
  const t = elapsed(step, now);
  return (
    <li className="relative flex gap-3 pb-5">
      {!last && <span aria-hidden className="absolute left-3 top-7 h-[calc(100%-1.5rem)] w-px bg-border" />}
      <Glyph state={step.state} />
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("text-sm", step.state === "skipped" || step.state === "pending" ? "text-fg-subtle" : "font-medium text-fg")}>{label}</span>
          {step.attempt > 1 && <span className="rounded bg-sidebar px-1.5 py-px font-mono text-[10.5px] text-fg-subtle">attempt {step.attempt}</span>}
          {extra}
          <span className="ml-auto flex items-center gap-2 font-mono text-[11px] text-fg-subtle">
            {step.cost_usd ? (
              <Tooltip content="LLM cost for this step">
                <span>{fmtMoney(step.cost_usd, true)}</span>
              </Tooltip>
            ) : null}
            {t != null && <span>{t < 60 ? `${t.toFixed(1)}s` : fmtDuration(t)}</span>}
          </span>
        </div>
        {step.sub_items && step.sub_items.length > 0 && (
          <ul className="mt-2 space-y-1">
            {step.sub_items.map((s) => (
              <li key={s.id} className="flex items-center gap-2 text-[13px]">
                <span className={cn("w-3 font-mono text-[11px]", s.state === "done" ? "text-success" : s.state === "running" ? "animate-pulse text-accent" : "text-fg-faint")}>
                  {SUB_GLYPH[s.state] ?? "○"}
                </span>
                <span className={s.state === "done" ? "text-fg-muted" : "text-fg"}>{s.label}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

export function PipelineStepper({ job }: { job: Job }) {
  const [now, setNow] = useState(() => Date.now());
  const live = job.status === "running" || job.status === "publishing";
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [live]);

  const by = Object.fromEntries(job.steps.map((s) => [s.step, s])) as Record<string, Step>;
  const get = (k: string): Step => by[k] ?? { step: k, label: k, state: "pending", attempt: 0 };
  const write = get("write_section");
  const fc = get("fact_check");
  const rev = get("revise_draft");
  const subsDone = write.sub_items?.filter((s) => s.state === "done").length ?? 0;
  // Fact-check and revise form one loop row, like the mockup.
  const loopState: Step["state"] =
    fc.state === "running" || rev.state === "running" ? "running" : fc.state === "failed" || rev.state === "failed" ? "failed" : fc.state;
  const loop: Step = { ...fc, state: loopState, attempt: 0, cost_usd: (fc.cost_usd ?? 0) + (rev.cost_usd ?? 0) || null };

  return (
    <ol aria-label="Pipeline progress" aria-live="polite">
      <Node step={get("ingest_video")} label="Ingest video" now={now} />
      <Node step={get("clean_transcript")} label="Clean transcript" now={now} />
      <Node step={get("plan_outline")} label="Plan outline" now={now} />
      <Node
        step={write}
        label="Write sections"
        now={now}
        extra={write.sub_items?.length ? <span className="text-xs text-fg-subtle">{subsDone} of {write.sub_items.length} · parallel</span> : null}
      />
      <Node step={get("assemble_post")} label="Assemble post" now={now} />
      <Node
        step={loop}
        now={now}
        label={
          <span>
            Fact-check <span className="mx-1 text-fg-faint">⇄</span> Revise
          </span>
        }
        extra={
          <span className="rounded bg-sidebar px-1.5 py-px font-mono text-[10.5px] text-fg-subtle">
            {job.revision_count > 0 ? `revision ${job.revision_count} of ${job.config.max_revisions}` : `max ${job.config.max_revisions} revisions`}
          </span>
        }
      />
      <Node step={get("prepare_metadata")} label="Prepare metadata" now={now} />
      <Node step={get("human_review")} label={<span>Human review · <span className="text-fg-subtle">you</span></span>} now={now} />
      <Node step={get("publish")} label={<span>Publish to dev.to · <span className="text-fg-subtle">you</span></span>} now={now} />
      <Node step={get("social_and_store")} label="Social posts" now={now} last />
    </ol>
  );
}

export function UsageMeter({ job }: { job: Job }) {
  const pct = job.budget_usd > 0 ? Math.min(100, (job.usage.cost_usd / job.budget_usd) * 100) : 0;
  const warn = pct >= 80;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-lg font-semibold">{fmtMoney(job.usage.cost_usd, true)}</span>
        <span className="text-xs text-fg-subtle">of {fmtMoney(job.budget_usd)}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-label="Budget used">
        <div className={cn("h-full rounded-full transition-[width] duration-500", warn ? "bg-warning" : "bg-accent")} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-[11px] text-fg-subtle">
        <span>
          {fmtTokens(job.usage.prompt_tokens)} in · {fmtTokens(job.usage.completion_tokens)} out
        </span>
        <span className={warn ? "text-warning" : ""}>{Math.round(pct)}%</span>
      </div>
    </div>
  );
}

function describe(ev: JobEvent): string {
  const d = ev.data as Record<string, string | number | undefined>;
  switch (ev.type) {
    case "sub_item_update":
      return `sub_item_update ${d.step}/${d.id} ${d.state}`;
    case "usage":
      return `usage +${Number(d.prompt_tokens ?? 0) + Number(d.completion_tokens ?? 0)} tok ${fmtMoney(Number(d.cost_usd ?? 0), true)} total`;
    case "step_started":
      return `step_started ${d.step}${Number(d.attempt) > 1 ? ` (attempt ${d.attempt})` : ""}`;
    case "step_finished":
      return `step_finished ${d.step} ${d.state ?? ""}`;
    case "step_failed":
      return `step_failed ${d.step}: ${d.message}`;
    case "status_changed":
      return `status ${d.status}${d.pending_action ? ` · waiting for ${d.pending_action}` : ""}`;
    case "interrupt":
      return `interrupt ${d.kind}`;
    default:
      return ev.type;
  }
}

export function ActivityLog({ events }: { events: JobEvent[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-[10px] border border-border bg-surface">
      <button className="flex w-full items-center gap-2 px-4 py-2.5 text-sm font-medium" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} /> Activity
        {events.length > 0 && <span className="ml-auto font-mono text-[11px] text-fg-faint">id {events[events.length - 1]?.id}</span>}
      </button>
      {open && (
        <div className="max-h-72 overflow-y-auto border-t border-border px-4 py-2 font-mono text-[11.5px] leading-6" role="log">
          {events.length === 0 && <p className="text-fg-subtle">Waiting for events…</p>}
          {[...events].reverse().map((e) => (
            <div key={`${e.id}-${e.type}`} className="flex gap-3">
              <span className="text-fg-faint">{new Date(e.at).toLocaleTimeString([], { hour12: false })}</span>
              <span className={e.type === "step_failed" ? "text-danger" : "text-fg-muted"}>{describe(e)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
