"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Check, ChevronDown, Loader2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Money, PageHeader, TimestampChip } from "@/components/common";
import { ModelPicker } from "@/components/jobs/ModelPicker";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/overlay";
import { Card, FieldError, Input, Label, Skeleton } from "@/components/ui/primitives";
import { ApiError, api, call, type Schemas } from "@/lib/api/client";
import { useDashboard, useIntegrations, useKeysConnected, useSettings, useStyleProfiles } from "@/lib/hooks/queries";
import { cn, fmtTimestamp } from "@/lib/utils";

type Preview = Schemas["VideoPreview"];
const ID_RE = /(?:v=|youtu\.be\/|shorts\/|embed\/|live\/)([A-Za-z0-9_-]{11})|^([A-Za-z0-9_-]{11})$/;

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function Eligibility({ p, model, onRetry }: { p: Preview; model: string; onRetry: () => void }) {
  if (p.eligible) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-success/30 bg-success-tint px-3 py-2 text-sm text-success" role="status">
        <Check className="h-4 w-4" /> Eligible
        {p.estimated_cost_usd && (
          <span className="text-fg-muted">
            · ≈ <Money usd={p.estimated_cost_usd.low} precise />–<Money usd={p.estimated_cost_usd.high} precise /> with{" "}
            <span className="font-mono">{model.split("/").pop()}</span>
          </span>
        )}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/30 bg-warning-bg px-3 py-2 text-sm text-warning-strong" role="alert">
      <AlertTriangle className="h-4 w-4" />
      <span>{p.ineligible_message ?? "This video can't be converted."}</span>
      {p.ineligible_reason === "already_published" && p.existing_article_url && (
        <a href={p.existing_article_url} target="_blank" rel="noreferrer" className="underline">
          View the existing post
        </a>
      )}
      {p.ineligible_reason === "fetch_blocked" && (
        <Button size="sm" onClick={onRetry} className="ml-auto">
          <RefreshCw className="h-3.5 w-3.5" /> Try again
        </Button>
      )}
    </div>
  );
}

function NewPostForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [url, setUrl] = useState(params.get("url") ?? "");
  const debounced = useDebounced(url.trim(), 400);
  const looksValid = ID_RE.test(debounced);
  const [showChapters, setShowChapters] = useState(false);
  const [advanced, setAdvanced] = useState(false);

  const settings = useSettings();
  const profiles = useStyleProfiles();
  const integrations = useIntegrations();
  const keys = useKeysConnected();
  const dash = useDashboard();

  const [attribution, setAttribution] = useState<"own_video" | "credited">("credited");
  const [styleId, setStyleId] = useState<string>("");
  const [model, setModel] = useState("");
  const [maxRevisions, setMaxRevisions] = useState(2);
  const [minFaith, setMinFaith] = useState(0.85);
  const [budget, setBudget] = useState(0.5);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const s = settings.data;
    if (!s) return;
    setAttribution(s.default_attribution);
    setModel(s.default_model);
    setMaxRevisions(s.default_max_revisions);
    setMinFaith(s.default_min_faithfulness);
    setBudget(s.default_budget_usd);
    setStyleId(s.default_style_profile_id ?? "");
  }, [settings.data]);

  const preview = useMutation({
    mutationFn: (u: string) => call(() => api.POST("/api/v1/videos/preview", { body: { url: u } })),
  });
  useEffect(() => {
    if (looksValid) preview.mutate(debounced);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced, looksValid]);

  const p = preview.data;
  const quota = dash.data?.quota;
  const quotaLeft = quota ? quota.jobs_per_day - quota.used_today : 1;

  const create = useMutation({
    mutationFn: () =>
      call(() =>
        api.POST("/api/v1/jobs", {
          body: {
            video_url: url.trim(),
            attribution_mode: attribution,
            style_profile_id: styleId || null,
            model,
            max_revisions: maxRevisions,
            min_faithfulness: minFaith,
            budget_usd: budget,
          },
        }),
      ),
    onSuccess: (r) => router.push(`/jobs/${r.job_id}`),
    onError: (e) => {
      if (e instanceof ApiError) {
        setErrors(e.fieldErrors);
        if (e.code === "keys_missing") router.push("/settings");
        toast.error(e.message);
      } else toast.error("Couldn't start the job.");
    },
  });

  const canSubmit = keys.ready && p?.eligible && quotaLeft > 0 && !!model && budget > 0;
  const submitHint = !keys.ready
    ? "Connect your API keys first"
    : quotaLeft <= 0
      ? "Daily limit reached"
      : p && !p.eligible
        ? "This video can't be converted"
        : null;

  const openrouterLast4 = integrations.data?.openrouter.last4;
  const channel = p?.channel_name || "the creator";
  const chapters = useMemo(() => p?.chapters ?? [], [p]);

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        crumbs={[{ label: "Jobs", href: "/dashboard" }, { label: "New post" }]}
        actions={quota && <span className="font-mono text-xs text-fg-subtle">{quota.used_today} / {quota.jobs_per_day} today</span>}
      />
      <h1 className="text-xl font-semibold tracking-tight">Turn a video into a post</h1>
      <p className="mt-1 text-sm text-fg-subtle">Paste any YouTube link — watch, youtu.be, shorts or with a timestamp.</p>

      <div className="relative mt-5">
        <Input
          className="h-11 pr-24 text-base"
          placeholder="https://youtu.be/…"
          value={url}
          autoFocus
          onChange={(e) => setUrl(e.target.value)}
          aria-label="YouTube URL"
          invalid={!!debounced && !looksValid}
        />
        <span className="absolute right-3 top-3 text-xs">
          {preview.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin text-fg-subtle" />
          ) : p ? (
            <span className="text-success">✓ Found</span>
          ) : null}
        </span>
        {debounced && !looksValid && <FieldError>That doesn't look like a YouTube link.</FieldError>}
        {preview.isError && <FieldError>{(preview.error as Error).message}</FieldError>}
      </div>

      {preview.isPending && !p && (
        <Card className="mt-4 flex gap-4 p-4">
          <Skeleton className="aspect-video w-40" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        </Card>
      )}

      {p && (
        <Card className="mt-4 animate-rise p-4">
          <div className="flex gap-4">
            <div className="relative w-40 shrink-0">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={p.thumbnail_url} alt="" className="aspect-video w-full rounded object-cover" />
              {p.duration_seconds > 0 && (
                <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 font-mono text-[10px] text-white">
                  {fmtTimestamp(p.duration_seconds)}
                </span>
              )}
            </div>
            <div className="min-w-0">
              <h2 className="font-medium leading-snug">{p.title || p.video_id}</h2>
              <p className="mt-0.5 text-sm text-fg-subtle">{p.channel_name}</p>
              <div className="mt-2 flex flex-wrap gap-1.5 font-mono text-[11px] text-fg-subtle">
                {p.transcript_language && <span className="rounded bg-sidebar px-1.5 py-0.5">transcript: {p.transcript_language}</span>}
                <span className="rounded bg-sidebar px-1.5 py-0.5">{chapters.length} chapters</span>
                <span className="rounded bg-sidebar px-1.5 py-0.5">{p.video_id}</span>
              </div>
            </div>
          </div>
          {chapters.length > 0 && (
            <div className="mt-3">
              <button className="flex items-center gap-1 text-xs text-fg-subtle hover:text-fg" onClick={() => setShowChapters((v) => !v)} aria-expanded={showChapters}>
                <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", showChapters && "rotate-180")} />
                Chapters · {showChapters ? "hide" : `show ${chapters.length}`}
              </button>
              {showChapters && (
                <ol className="mt-2 space-y-1 text-sm">
                  {chapters.map((c) => (
                    <li key={c.start} className="flex items-center gap-2">
                      <TimestampChip seconds={c.start} />
                      {c.title}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
          <div className="mt-4">
            <Eligibility p={p} model={model} onRetry={() => preview.mutate(debounced)} />
          </div>
        </Card>
      )}

      <div className={cn("mt-6 space-y-5", !p?.eligible && "pointer-events-none opacity-50")} aria-disabled={!p?.eligible}>
        <div>
          <Label>Attribution</Label>
          <div className="inline-flex rounded-lg bg-sidebar p-1" role="radiogroup" aria-label="Attribution">
            {(
              [
                ["own_video", "It's my video"],
                ["credited", "Credit the creator"],
              ] as const
            ).map(([k, l]) => (
              <button
                key={k}
                role="radio"
                aria-checked={attribution === k}
                onClick={() => setAttribution(k)}
                className={cn("rounded-md px-3 py-1 text-sm", attribution === k ? "bg-surface font-medium shadow-sm" : "text-fg-subtle")}
              >
                {l}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-fg-subtle">
            {attribution === "credited"
              ? `Adds a "Based on a video by ${channel}" block with an embed at the top.`
              : "Adds a short note linking to your video, with an embed at the top."}
          </p>
        </div>

        <div>
          <Label htmlFor="style">Style profile</Label>
          <div className="flex items-center gap-3">
            <select
              id="style"
              className="h-9 flex-1 rounded-md border border-border bg-surface px-2 text-sm"
              value={styleId}
              onChange={(e) => setStyleId(e.target.value)}
            >
              <option value="">No style profile</option>
              {profiles.data?.map((sp) => (
                <option key={sp.id} value={sp.id}>
                  {sp.name}
                </option>
              ))}
            </select>
            <Link href="/settings/style-profiles" className="text-xs text-accent hover:underline">
              Create one
            </Link>
          </div>
        </div>

        <div>
          <Label>Model</Label>
          {model ? (
            <ModelPicker value={model} onChange={setModel} videoId={p?.video_id} budgetUsd={budget} keyLast4={openrouterLast4} />
          ) : (
            <Skeleton className="h-9 w-full" />
          )}
          <FieldError>{errors.model}</FieldError>
        </div>

        <div>
          <button className="flex items-center gap-1 text-sm text-fg-muted hover:text-fg" onClick={() => setAdvanced((v) => !v)} aria-expanded={advanced}>
            <ChevronDown className={cn("h-4 w-4 transition-transform", advanced && "rotate-180")} /> Advanced
          </button>
          {advanced && (
            <div className="mt-3 grid gap-5 rounded-lg border border-border p-4 sm:grid-cols-3">
              <div>
                <Label>Max auto-revisions</Label>
                <div className="flex items-center gap-2">
                  <Button size="icon" variant="outline" aria-label="Fewer revisions" onClick={() => setMaxRevisions((v) => Math.max(0, v - 1))}>
                    −
                  </Button>
                  <span className="w-6 text-center font-mono" aria-live="polite">
                    {maxRevisions}
                  </span>
                  <Button size="icon" variant="outline" aria-label="More revisions" onClick={() => setMaxRevisions((v) => Math.min(3, v + 1))}>
                    +
                  </Button>
                </div>
              </div>
              <div>
                <Label>
                  Min. faithfulness <span className="ml-1 font-mono text-fg">{minFaith.toFixed(2)}</span>
                </Label>
                <Slider label="Minimum faithfulness" min={0.5} max={1} step={0.05} value={[minFaith]} onValueChange={(v) => setMinFaith(v[0] ?? 0.85)} />
              </div>
              <div>
                <Label htmlFor="budget">Job budget</Label>
                <div className="relative">
                  <span className="absolute left-3 top-2 text-sm text-fg-subtle">$</span>
                  <Input
                    id="budget"
                    type="number"
                    min={0.01}
                    step={0.05}
                    className="pl-6 font-mono"
                    value={budget}
                    onChange={(e) => setBudget(Number(e.target.value))}
                    invalid={!!errors.budget_usd}
                  />
                </div>
                <FieldError>{errors.budget_usd}</FieldError>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="mt-8 flex items-center justify-between border-t border-border pt-5">
        <p className="text-xs text-fg-subtle">You'll review the draft before anything is published.</p>
        <div className="flex items-center gap-3">
          {submitHint && <span className="text-xs text-fg-subtle">{submitHint}</span>}
          <Button variant="primary" size="lg" disabled={!canSubmit} loading={create.isPending} onClick={() => create.mutate()}>
            Start writing
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function NewPostPage() {
  return (
    <Suspense>
      <NewPostForm />
    </Suspense>
  );
}
