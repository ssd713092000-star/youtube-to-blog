"use client";

import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { CharCounter, ConfirmDialog, ErrorState, PageHeader, TimestampChip } from "@/components/common";
import { DraftDiff, MarkdownPreview } from "@/components/review/Markdown";
import { ClaimList, FaithfulnessGauge, TagInput, TitlePicker } from "@/components/review/Quality";
import { YouTubePlayer, type PlayerHandle } from "@/components/review/YouTubePlayer";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlay";
import { Card, Kbd, Skeleton, Textarea } from "@/components/ui/primitives";
import { api, call } from "@/lib/api/client";
import { useDraft, useDrafts, useFactCheck, useJob, useReview } from "@/lib/hooks/queries";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { useResumeAction } from "@/lib/hooks/useResumeAction";
import { cn, fmtRelative } from "@/lib/utils";

const MarkdownEditor = dynamic(() => import("@/components/review/MarkdownEditor"), {
  ssr: false,
  loading: () => <Skeleton className="h-[60vh] w-full" />,
});

const QUICK_FEEDBACK = ["Shorter intro", "Add code examples", "More beginner friendly", "Fix unsupported claims"];

type ReviewArgs = {
  action: "approve" | "edit" | "revise" | "abort";
  markdown?: string;
  title?: string;
  tags?: string[];
  description?: string;
  feedback?: string;
  checkpoint: string;
};

function storageKey(jobId: string, rev: number) {
  return `t2d_draft_${jobId}_${rev}`;
}

function wordCount(md: string) {
  return md.split(/\s+/).filter(Boolean).length;
}

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const job = useJob(id);
  useJobEvents(id);
  const review = useReview(id, job.data?.pending_action === "draft_review");
  const drafts = useDrafts(id);
  const fc = useFactCheck(id);
  const rev = review.data?.draft_rev;
  const draft = useDraft(id, rev);

  const [compareRev, setCompareRev] = useState<number | null>(null);
  const [viewRev, setViewRev] = useState<number | null>(null);
  const viewed = useDraft(id, viewRev);
  const compare = useDraft(id, compareRev);

  const [md, setMd] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [description, setDescription] = useState("");
  const [tab, setTab] = useState("edit");
  const [mobileTab, setMobileTab] = useState("draft");
  const [reviseOpen, setReviseOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [abortOpen, setAbortOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [restored, setRestored] = useState<string | null>(null);
  const player = useRef<PlayerHandle>(null);
  const previewRef = useRef<HTMLDivElement>(null);

  // Initialise editable fields once the review payload + draft arrive.
  useEffect(() => {
    if (!review.data || draft.data == null || md !== null) return;
    setTitle(review.data.title);
    setTags(review.data.tags);
    setDescription(review.data.description);
    const saved = typeof window !== "undefined" ? localStorage.getItem(storageKey(id, review.data.draft_rev)) : null;
    if (saved && saved !== draft.data.markdown) setRestored(saved);
    setMd(draft.data.markdown);
  }, [review.data, draft.data, md, id]);

  const original = draft.data?.markdown ?? "";
  const dirty = md !== null && md !== original;
  const metaChanged = !!review.data && (title !== review.data.title || description !== review.data.description || tags.join() !== review.data.tags.join());

  // Unsaved-changes guard
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  const saveLocal = useCallback(() => {
    if (md != null && rev != null) {
      localStorage.setItem(storageKey(id, rev), md);
      toast.success("Draft saved on this device");
    }
  }, [md, rev, id]);

  // Autosave locally every few seconds while editing.
  useEffect(() => {
    if (!dirty || rev == null || md == null) return;
    const t = setTimeout(() => localStorage.setItem(storageKey(id, rev), md), 1500);
    return () => clearTimeout(t);
  }, [dirty, md, rev, id]);

  const submit = useResumeAction(
    id,
    (a: ReviewArgs, key) =>
      call(() =>
        api.POST("/api/v1/jobs/{job_id}/review", {
          params: { path: { job_id: id }, header: { "idempotency-key": key } },
          body: {
            action: a.action,
            markdown: a.markdown ?? null,
            title: a.title ?? null,
            tags: a.tags ?? null,
            description: a.description ?? null,
            feedback: a.feedback ?? null,
            expected_checkpoint_id: a.checkpoint,
          },
        }),
      ),
    {
      label: "review",
      onSuccess: () => {
        if (rev != null) localStorage.removeItem(storageKey(id, rev));
        router.push(`/jobs/${id}`);
      },
    },
  );

  const checkpoint = job.data?.checkpoint_id ?? "";
  const approve = useCallback(() => {
    if (!review.data || md == null) return;
    if (!title.trim()) return toast.error("Pick or write a title.");
    const meta = metaChanged ? { title, tags, description } : {};
    void submit.run(dirty ? { action: "edit", markdown: md, title, tags, description, checkpoint } : { action: "approve", ...meta, checkpoint });
  }, [review.data, md, title, tags, description, metaChanged, dirty, checkpoint, submit]);

  // Keyboard shortcuts
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        saveLocal();
      } else if (mod && e.key === "Enter") {
        e.preventDefault();
        approve();
      } else if (e.key === "?" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) && !(e.target as HTMLElement)?.closest?.(".cm-editor")) {
        setHelpOpen(true);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [saveLocal, approve]);

  const seek = useCallback((s: number) => player.current?.seekTo(s), []);
  const unsupported = useMemo(() => (fc.data?.claims ?? []).filter((c) => !c.supported).map((c) => ({ text: c.text, evidence: c.evidence })), [fc.data]);

  const focusClaim = (text: string) => {
    setTab("preview");
    setMobileTab("draft");
    setTimeout(() => {
      const el = Array.from(previewRef.current?.querySelectorAll<HTMLElement>("[data-claim]") ?? []).find((n) => n.dataset.claim === text);
      el?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 50);
  };

  if (job.data && job.data.pending_action !== "draft_review" && !submit.pending) {
    return (
      <div className="mx-auto max-w-lg py-16 text-center">
        <p className="text-sm text-fg-subtle">This job isn't waiting for a draft review right now.</p>
        <Button className="mt-4" onClick={() => router.push(`/jobs/${id}`)}>
          Back to the job
        </Button>
      </div>
    );
  }
  if (review.isError) return <ErrorState error={review.error} onRetry={() => void review.refetch()} />;
  if (!job.data || !review.data || md === null) {
    return (
      <div className="grid gap-5 lg:grid-cols-[300px_1fr_320px]">
        <Skeleton className="h-[70vh]" />
        <Skeleton className="h-[70vh]" />
        <Skeleton className="h-[70vh]" />
      </div>
    );
  }

  const r = review.data;
  const shownMd = viewRev != null && viewRev !== rev ? (viewed.data?.markdown ?? "") : md;
  const readOnly = viewRev != null && viewRev !== rev;
  const words = wordCount(shownMd);

  const source = (
    <div className="space-y-4">
      <YouTubePlayer ref={player} videoId={job.data.video_id} title={job.data.video_title} />
      <div className="space-y-1 text-sm">
        {r.angle && (
          <p>
            <span className="text-fg-subtle">Angle · </span>
            {r.angle}
          </p>
        )}
        {r.target_reader && (
          <p>
            <span className="text-fg-subtle">Reader · </span>
            {r.target_reader}
          </p>
        )}
      </div>
      <ol className="space-y-3">
        {r.outline.map((s) => (
          <li key={s.id}>
            <div className="flex items-center gap-2">
              <TimestampChip seconds={s.start} onSeek={seek} />
              <span className="text-sm font-medium">{s.heading}</span>
            </div>
            {s.key_points.length > 0 && <p className="mt-0.5 pl-[3.25rem] text-xs text-fg-subtle">{s.key_points.join(" · ")}</p>}
          </li>
        ))}
      </ol>
    </div>
  );

  const draftPane = (
    <Card className="flex min-h-[70vh] flex-col">
      <Tabs value={tab} onValueChange={setTab} className="flex flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
          <select
            aria-label="Draft version"
            className="h-7 rounded-md border border-border bg-surface px-2 font-mono text-xs"
            value={viewRev ?? rev}
            onChange={(e) => setViewRev(Number(e.target.value) === rev ? null : Number(e.target.value))}
          >
            {drafts.data?.map((d) => (
              <option key={d.rev} value={d.rev}>
                rev {d.rev} · {d.kind.replace("_", " ")} · {fmtRelative(d.created_at)}
              </option>
            ))}
          </select>
          <TabsList>
            <TabsTrigger value="edit">Edit</TabsTrigger>
            <TabsTrigger value="preview">Preview</TabsTrigger>
            <TabsTrigger value="diff">Diff</TabsTrigger>
          </TabsList>
          {dirty && <span className="rounded bg-warning-bg px-1.5 py-0.5 text-[11px] text-warning-strong">Unsaved edits</span>}
          <span className="ml-auto font-mono text-[11px] text-fg-subtle">
            {words.toLocaleString()} words · {shownMd.length.toLocaleString()} chars · {Math.max(1, Math.round(words / 220))} min
          </span>
        </div>
        {restored && (
          <div className="flex items-center gap-3 border-b border-border bg-accent-tint/50 px-3 py-2 text-xs">
            You have unsaved edits from earlier on this device.
            <Button size="sm" variant="primary" onClick={() => { setMd(restored); setRestored(null); }}>
              Restore
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { localStorage.removeItem(storageKey(id, r.draft_rev)); setRestored(null); }}>
              Discard
            </Button>
          </div>
        )}
        <TabsContent value="edit" className="flex-1">
          {readOnly ? (
            <div className="p-4">
              <p className="mb-3 text-xs text-fg-subtle">Viewing an older version (read-only).</p>
              <MarkdownPreview markdown={shownMd} onSeek={seek} />
            </div>
          ) : (
            <MarkdownEditor value={md} onChange={setMd} />
          )}
        </TabsContent>
        <TabsContent value="preview" className="flex-1 overflow-y-auto p-5" ref={previewRef}>
          <MarkdownPreview markdown={shownMd} claims={unsupported} onSeek={seek} />
        </TabsContent>
        <TabsContent value="diff" className="flex-1 p-3">
          <div className="mb-2 flex items-center gap-2 text-xs text-fg-subtle">
            Compare with
            <select
              aria-label="Compare with version"
              className="h-7 rounded-md border border-border bg-surface px-2 font-mono text-xs"
              value={compareRev ?? ""}
              onChange={(e) => setCompareRev(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">— pick a version —</option>
              {drafts.data?.filter((d) => d.rev !== rev).map((d) => (
                <option key={d.rev} value={d.rev}>
                  rev {d.rev} · {d.kind.replace("_", " ")}
                </option>
              ))}
            </select>
          </div>
          {compareRev == null ? (
            <p className="text-sm text-fg-subtle">Pick an earlier version to see what changed.</p>
          ) : compare.data ? (
            <DraftDiff before={compare.data.markdown} after={md} />
          ) : (
            <Skeleton className="h-64" />
          )}
        </TabsContent>
      </Tabs>
    </Card>
  );

  const quality = (
    <div className="space-y-5">
      <Card className="space-y-4 p-4">
        <FaithfulnessGauge score={r.faithfulness_score} min={r.min_faithfulness} revisions={r.revision_count} />
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-lg bg-sidebar px-3 py-2">
            <div className="text-xs text-fg-subtle">Readability</div>
            <div className="font-mono font-semibold">{r.quality_scores?.readability ?? "—"}/10</div>
          </div>
          <div className="rounded-lg bg-sidebar px-3 py-2">
            <div className="text-xs text-fg-subtle">Structure</div>
            <div className="font-mono font-semibold">{r.quality_scores?.structure ?? "—"}/10</div>
          </div>
        </div>
        {fc.data && <ClaimList claims={fc.data.claims} onSeek={seek} onFocus={focusClaim} />}
      </Card>
      <Card className="space-y-4 p-4">
        <TitlePicker options={r.title_options} value={title} onChange={setTitle} />
        <div>
          <div className="mb-1.5 flex items-center justify-between text-xs font-medium text-fg-subtle">
            Description <CharCounter value={description.length} max={150} />
          </div>
          <Textarea rows={3} maxLength={150} value={description} onChange={(e) => setDescription(e.target.value)} aria-label="Description" />
        </div>
        <TagInput value={tags} onChange={setTags} />
      </Card>
    </div>
  );

  return (
    <div className="pb-24">
      <PageHeader
        crumbs={[{ label: "Jobs", href: "/dashboard" }, { label: job.data.video_title || job.data.short_id, href: `/jobs/${id}` }, { label: "Review" }]}
        actions={
          <Button variant="ghost" size="icon" aria-label="Keyboard shortcuts" onClick={() => setHelpOpen(true)}>
            ?
          </Button>
        }
      />

      {/* Desktop: three columns */}
      <div className="hidden gap-5 lg:grid lg:grid-cols-[minmax(260px,300px)_1fr_minmax(280px,320px)]">
        <aside className="lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:self-start lg:overflow-y-auto">{source}</aside>
        {draftPane}
        <aside>{quality}</aside>
      </div>

      {/* Tablet / mobile: tabs */}
      <div className="lg:hidden">
        <Tabs value={mobileTab} onValueChange={setMobileTab}>
          <TabsList className="mb-4 w-full">
            <TabsTrigger value="draft" className="flex-1">Draft</TabsTrigger>
            <TabsTrigger value="source" className="flex-1">Video & outline</TabsTrigger>
            <TabsTrigger value="quality" className="flex-1">Quality</TabsTrigger>
          </TabsList>
          <TabsContent value="draft" forceMount className={cn(mobileTab !== "draft" && "hidden")}>
            {draftPane}
          </TabsContent>
          <TabsContent value="source" forceMount className={cn(mobileTab !== "source" && "hidden")}>
            {source}
          </TabsContent>
          <TabsContent value="quality">{quality}</TabsContent>
        </Tabs>
      </div>

      {/* Sticky action bar */}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface/95 backdrop-blur md:left-[216px]">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-3 px-4 py-3 sm:px-8">
          <Button variant="danger" onClick={() => setAbortOpen(true)} disabled={submit.pending}>
            Abort
          </Button>
          <span className="hidden items-center gap-1.5 text-xs text-fg-subtle md:flex">
            <Kbd>⌘S</Kbd> save · <Kbd>⌘↵</Kbd> approve
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button onClick={() => setReviseOpen(true)} disabled={submit.pending}>
              Request revision
            </Button>
            <Button variant="primary" onClick={approve} loading={submit.pending}>
              {submit.pending ? "Sending to the pipeline…" : dirty ? "Save edits & approve" : "Approve"}
            </Button>
          </div>
        </div>
      </div>

      <Dialog open={reviseOpen} onOpenChange={setReviseOpen}>
        <DialogContent title="Request a revision" description="The writer revises the affected parts, then the post is fact-checked again." side="right">
          <div className="space-y-3">
            <div className="flex flex-wrap gap-1.5">
              {QUICK_FEEDBACK.map((q) => (
                <button key={q} className="rounded-full border border-border px-2.5 py-1 text-xs hover:border-accent hover:text-accent" onClick={() => setFeedback((f) => (f ? `${f}\n${q}` : q))}>
                  + {q}
                </button>
              ))}
            </div>
            <Textarea rows={8} value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="What should change?" aria-label="Revision feedback" maxLength={4000} />
            {dirty && <p className="text-xs text-warning">Your unsaved edits will be discarded — the writer revises the last generated draft.</p>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setReviseOpen(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={!feedback.trim()}
                loading={submit.pending}
                onClick={async () => {
                  const ok = await submit.run({ action: "revise", feedback: feedback.trim(), checkpoint });
                  if (ok) setReviseOpen(false);
                }}
              >
                Send to the writer
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={abortOpen}
        onOpenChange={setAbortOpen}
        title="Abort this post?"
        body="The pipeline stops here and nothing is published to dev.to. The draft stays viewable in the job's history."
        confirmLabel="Abort"
        danger
        loading={submit.pending}
        onConfirm={() => void submit.run({ action: "abort", checkpoint })}
      />

      <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
        <DialogContent title="Keyboard shortcuts">
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt><Kbd>⌘/Ctrl S</Kbd></dt>
            <dd>Save your edits on this device</dd>
            <dt><Kbd>⌘/Ctrl ↵</Kbd></dt>
            <dd>Approve (saves edits first)</dd>
            <dt><Kbd>?</Kbd></dt>
            <dd>Show this dialog</dd>
          </dl>
        </DialogContent>
      </Dialog>
    </div>
  );
}

