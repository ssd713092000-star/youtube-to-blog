"use client";

import { Check, ChevronRight, Copy, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { Input } from "@/components/ui/primitives";
import type { Schemas } from "@/lib/api/client";
import type { ConnectionState } from "@/lib/hooks/useJobEvents";
import { cn, fmtMoney, fmtTimestamp } from "@/lib/utils";

type JobStatus = Schemas["JobSummary"]["status"];

// Status always pairs a glyph + label with colour (never colour alone).
const STATUS: Record<JobStatus, { label: string; glyph: string; cls: string }> = {
  queued: { label: "Queued", glyph: "◌", cls: "bg-sidebar text-fg-muted" },
  running: { label: "Running", glyph: "●", cls: "bg-accent-tint text-accent" },
  publishing: { label: "Publishing", glyph: "●", cls: "bg-accent-tint text-accent" },
  awaiting_review: { label: "Awaiting review", glyph: "❚❚", cls: "bg-warning-bg text-warning-strong" },
  awaiting_publish: { label: "Awaiting publish", glyph: "❚❚", cls: "bg-warning-bg text-warning-strong" },
  completed: { label: "Completed", glyph: "✓", cls: "bg-success-bg text-success" },
  rejected: { label: "Rejected", glyph: "⊘", cls: "bg-sidebar text-fg-subtle" },
  failed: { label: "Failed", glyph: "✕", cls: "bg-danger-bg text-danger" },
  cancelled: { label: "Cancelled", glyph: "⊘", cls: "bg-sidebar text-fg-subtle" },
};

export function StatusBadge({ status, detail, className }: { status: JobStatus; detail?: string | null; className?: string }) {
  const s = STATUS[status];
  const live = status === "running" || status === "publishing";
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium whitespace-nowrap", s.cls, className)}>
      <span aria-hidden className={cn("text-[10px]", live && "animate-pulse")}>
        {s.glyph}
      </span>
      {s.label}
      {detail && <span className="font-normal opacity-80">· {detail}</span>}
    </span>
  );
}

export function scoreTone(score: number | null | undefined, min = 0.85): "good" | "warn" | "bad" | "none" {
  if (score == null) return "none";
  if (score >= min) return "good";
  if (score >= 0.7) return "warn";
  return "bad";
}

export function ScorePill({ score, min }: { score: number | null | undefined; min?: number }) {
  const tone = scoreTone(score, min);
  if (tone === "none") return <span className="text-fg-faint">—</span>;
  const cls = { good: "bg-success-bg text-success", warn: "bg-warning-bg text-warning-strong", bad: "bg-danger-bg text-danger" }[tone];
  const label = { good: "good", warn: "borderline", bad: "low" }[tone];
  return (
    <span className={cn("inline-flex rounded px-1.5 py-0.5 font-mono text-xs", cls)} title={`Faithfulness ${label}`}>
      {score!.toFixed(2)}
    </span>
  );
}

export function TimestampChip({ seconds, onSeek, className }: { seconds: number; onSeek?: (s: number) => void; className?: string }) {
  const label = fmtTimestamp(seconds);
  const cls = cn(
    "inline-flex items-center rounded border border-border bg-sidebar px-1.5 py-0.5 font-mono text-[11px] text-fg-muted",
    onSeek && "hover:border-accent hover:text-accent",
    className,
  );
  if (!onSeek) return <span className={cls}>{label}</span>;
  return (
    <button type="button" className={cls} onClick={() => onSeek(seconds)} aria-label={`Play from ${label}`}>
      {label}
    </button>
  );
}

export function Money({ usd, precise, className }: { usd: number | null | undefined; precise?: boolean; className?: string }) {
  return <span className={cn("font-mono tabular-nums", className)}>{fmtMoney(usd, precise)}</span>;
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      variant={copied ? "ghost" : "outline"}
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
      }}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
      <span aria-live="polite">{copied ? "Copied" : label}</span>
    </Button>
  );
}

export function CharCounter({ value, max, soft }: { value: number; max: number; soft?: number }) {
  const over = value > max;
  const warn = soft != null && value > soft;
  return (
    <span className={cn("font-mono text-[11px]", over ? "text-danger" : warn ? "text-warning" : "text-fg-faint")}>
      {value}/{soft ?? max}
    </span>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[10px] border border-dashed border-border-strong bg-surface px-6 py-14 text-center">
      <h3 className="text-sm font-semibold">{title}</h3>
      {body && <div className="mt-1 max-w-md text-sm text-fg-subtle">{body}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const e = error as { message?: string; requestId?: string | null; status?: number };
  return (
    <div role="alert" className="rounded-[10px] border border-danger/30 bg-danger-bg/40 px-5 py-4 text-sm">
      <p className="font-medium text-danger">{e?.status === 404 ? "Not found." : "Something went wrong."}</p>
      <p className="mt-1 text-fg-muted">{e?.message ?? "Please try again."}</p>
      <div className="mt-3 flex items-center gap-3">
        {onRetry && (
          <Button size="sm" onClick={onRetry}>
            <RefreshCw className="h-3.5 w-3.5" /> Retry
          </Button>
        )}
        {e?.requestId && <span className="font-mono text-[11px] text-fg-subtle">Request ID {e.requestId}</span>}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  danger,
  typedConfirm,
  loading,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  body: React.ReactNode;
  confirmLabel: string;
  danger?: boolean;
  typedConfirm?: string;
  loading?: boolean;
  onConfirm: () => void;
}) {
  const [typed, setTyped] = useState("");
  const ok = !typedConfirm || typed.trim().toLowerCase() === typedConfirm.toLowerCase();
  return (
    <Dialog open={open} onOpenChange={(v) => { setTyped(""); onOpenChange(v); }}>
      <DialogContent title={title}>
        <div className="space-y-4 text-sm text-fg-muted">
          <div>{body}</div>
          {typedConfirm && (
            <div>
              <p className="mb-1.5 text-xs">
                Type <span className="font-mono font-semibold text-fg">{typedConfirm}</span> to confirm.
              </p>
              <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus aria-label="Confirmation" />
            </div>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant={danger ? "danger" : "primary"} disabled={!ok} loading={loading} onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function ConnectionIndicator({ state }: { state: ConnectionState }) {
  const map = {
    live: { label: "Live", cls: "text-accent", dot: "bg-accent animate-pulse" },
    connecting: { label: "Connecting", cls: "text-fg-subtle", dot: "bg-fg-faint" },
    reconnecting: { label: "Reconnecting", cls: "text-warning", dot: "bg-warning animate-pulse" },
    offline: { label: "Polling", cls: "text-fg-subtle", dot: "bg-fg-faint" },
  }[state];
  return (
    <span className={cn("inline-flex items-center gap-1.5 font-mono text-[11px]", map.cls)} aria-live="polite">
      <span className={cn("h-1.5 w-1.5 rounded-full", map.dot)} />
      {map.label}
    </span>
  );
}

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm text-fg-subtle">
      {items.map((it, i) => (
        <span key={i} className="flex min-w-0 items-center gap-1.5">
          {i > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-fg-faint" aria-hidden />}
          {it.href ? (
            <Link href={it.href} className="truncate hover:text-fg">
              {it.label}
            </Link>
          ) : (
            <span className="truncate font-medium text-fg">{it.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

export function PageHeader({ crumbs, title, actions }: { crumbs?: { label: string; href?: string }[]; title?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        {crumbs && <Breadcrumbs items={crumbs} />}
        {title && <h1 className="mt-1 text-xl font-semibold tracking-tight">{title}</h1>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
