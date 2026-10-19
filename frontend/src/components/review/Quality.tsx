"use client";

import { X } from "lucide-react";
import { useState } from "react";

import { CharCounter, TimestampChip } from "@/components/common";
import { Input } from "@/components/ui/primitives";
import type { Schemas } from "@/lib/api/client";
import { cn } from "@/lib/utils";

export function FaithfulnessGauge({ score, min, revisions }: { score: number | null | undefined; min: number; revisions: number }) {
  const lo = 0.5;
  const pos = (v: number) => `${Math.max(0, Math.min(1, (v - lo) / (1 - lo))) * 100}%`;
  const ok = score != null && score >= min;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium text-fg-subtle">Faithfulness</span>
        <span className={cn("font-mono text-2xl font-semibold", ok ? "text-success" : "text-warning")}>{score?.toFixed(2) ?? "—"}</span>
      </div>
      <div className="relative mt-2 h-2 rounded-full bg-border" role="meter" aria-valuemin={lo} aria-valuemax={1} aria-valuenow={score ?? undefined} aria-label="Faithfulness score">
        <div
          className={cn("h-full rounded-full transition-[width] duration-700 ease-out", ok ? "bg-success" : "bg-warning")}
          style={{ width: score != null ? pos(score) : "0%" }}
        />
        <span className="absolute -top-1 h-4 w-0.5 bg-fg" style={{ left: pos(min) }} aria-hidden />
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10.5px] text-fg-faint">
        <span>0.50</span>
        <span className={ok ? "" : "text-warning"}>
          ▲ your min {min.toFixed(2)}
          {revisions > 0 && ` · after ${revisions} revision${revisions > 1 ? "s" : ""}`}
        </span>
        <span>1.0</span>
      </div>
    </div>
  );
}

export function ClaimList({ claims, onSeek, onFocus }: { claims: Schemas["ClaimOut"][]; onSeek?: (s: number) => void; onFocus?: (text: string) => void }) {
  const [onlyBad, setOnlyBad] = useState(true);
  const bad = claims.filter((c) => !c.supported);
  const shown = onlyBad ? bad : claims;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-fg-subtle">
          Claims · {bad.length} of {claims.length} {bad.length > 0 && "⚠"}
        </span>
        <label className="flex items-center gap-1.5 text-xs text-fg-subtle">
          <input type="checkbox" checked={onlyBad} onChange={(e) => setOnlyBad(e.target.checked)} className="accent-[var(--accent)]" />
          Unsupported only
        </label>
      </div>
      {shown.length === 0 ? (
        <p className="text-sm text-fg-subtle">{onlyBad ? "Every checked claim is supported by the transcript." : "No claims were checked."}</p>
      ) : (
        <ul className="space-y-2">
          {shown.map((c, i) => (
            <li key={i} className={cn("rounded-lg border p-2.5 text-sm", c.supported ? "border-border" : "border-warning/40 bg-warning-bg/40")}>
              <button className="w-full text-left" onClick={() => onFocus?.(c.text)}>
                <span className="flex gap-2">
                  <span aria-label={c.supported ? "Supported" : "Unsupported"} className={c.supported ? "text-success" : "text-warning"}>
                    {c.supported ? "✓" : "⚠"}
                  </span>
                  <span className="font-medium">{c.text}</span>
                </span>
              </button>
              {c.evidence && <p className="mt-1 pl-5 text-xs text-fg-subtle">{c.evidence}</p>}
              {c.timestamp_seconds != null && (
                <div className="mt-1.5 pl-5">
                  <TimestampChip seconds={c.timestamp_seconds} onSeek={onSeek} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function TitlePicker({ options, value, onChange }: { options: string[]; value: string; onChange: (v: string) => void }) {
  const custom = !options.includes(value);
  return (
    <fieldset>
      <legend className="mb-1.5 flex w-full items-center justify-between text-xs font-medium text-fg-subtle">
        Title <CharCounter value={value.length} max={128} soft={80} />
      </legend>
      <div className="space-y-1.5">
        {options.map((o) => (
          <label key={o} className={cn("flex cursor-pointer gap-2 rounded-lg border px-2.5 py-2 text-sm", value === o ? "border-accent bg-accent-tint/50" : "border-border hover:border-border-strong")}>
            <input type="radio" name="title" checked={value === o} onChange={() => onChange(o)} className="mt-0.5 accent-[var(--accent)]" />
            {o}
          </label>
        ))}
        <label className={cn("flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm", custom ? "border-accent" : "border-border")}>
          <input type="radio" name="title" checked={custom} onChange={() => onChange("")} className="accent-[var(--accent)]" />
          <input
            className="h-7 flex-1 bg-transparent text-sm outline-none placeholder:text-fg-faint"
            placeholder="Custom…"
            value={custom ? value : ""}
            maxLength={128}
            onChange={(e) => onChange(e.target.value)}
            aria-label="Custom title"
          />
        </label>
      </div>
    </fieldset>
  );
}

export function cleanTag(t: string): string {
  return t.toLowerCase().replace(/[^a-z0-9]/g, "");
}

export function TagInput({ value, onChange, max = 4 }: { value: string[]; onChange: (v: string[]) => void; max?: number }) {
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const t = cleanTag(raw);
    if (!t || value.includes(t) || value.length >= max) return;
    onChange([...value, t]);
    setDraft("");
  };
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-xs font-medium text-fg-subtle">
        Tags <span className="font-mono text-[11px] text-fg-faint">{value.length}/{max}</span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-border p-1.5">
        {value.map((t) => (
          <span key={t} className="inline-flex items-center gap-1 rounded bg-sidebar px-2 py-0.5 font-mono text-xs">
            #{t}
            <button aria-label={`Remove ${t}`} onClick={() => onChange(value.filter((x) => x !== t))} className="text-fg-faint hover:text-fg">
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        {value.length < max && (
          <Input
            className="h-7 w-28 flex-1 border-0 px-1"
            placeholder="add tag"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === "," || e.key === " ") {
                e.preventDefault();
                add(draft);
              } else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
            }}
            onBlur={() => draft && add(draft)}
            aria-label="Add tag"
          />
        )}
      </div>
      <p className="mt-1 text-[11px] text-fg-faint">Lowercase letters and digits only, max {max}.</p>
    </div>
  );
}
