"use client";

import { Command } from "cmdk";
import { AlertTriangle, Check, ChevronDown } from "lucide-react";
import { useMemo, useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/overlay";
import type { Schemas } from "@/lib/api/client";
import { useModels, type ModelQuery } from "@/lib/hooks/queries";
import { cn, fmtMoney } from "@/lib/utils";

type Model = Schemas["ModelOut"];

const FILTERS = [
  { key: "all", label: "All" },
  { key: "cheap", label: "Under $1 / Mtok" },
  { key: "ctx", label: "≥ 128k context" },
  { key: "used", label: "Used before" },
] as const;

function ctx(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(n % 1_000_000 ? 1 : 0)}M` : `${Math.round(n / 1000)}k`;
}

function price(m: Model): string {
  const f = (v: number) => (v >= 10 ? `$${v.toFixed(0)}` : `$${v.toFixed(2)}`);
  return `${f(m.price_per_mtok_in)} / ${f(m.price_per_mtok_out)}`;
}

function estimate(m: Model): string {
  if (!m.estimate_usd) return "—";
  return `${fmtMoney(m.estimate_usd.low, true)}–${fmtMoney(m.estimate_usd.high, true).replace("$", "")}`;
}

export function ModelPicker({
  value,
  onChange,
  videoId,
  budgetUsd,
  keyLast4,
}: {
  value: string;
  onChange: (id: string) => void;
  videoId?: string;
  budgetUsd?: number;
  keyLast4?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [sort, setSort] = useState<"price" | "context" | "name">("price");

  const params: ModelQuery = {
    q: q || undefined,
    sort,
    video_id: videoId,
    budget_usd: budgetUsd,
    max_price_mtok: filter === "cheap" ? 1 : undefined,
    min_context: filter === "ctx" ? 128_000 : undefined,
    used_before: filter === "used" ? true : undefined,
  };
  const { data, isFetching } = useModels(params);
  const all = useModels({ video_id: videoId, budget_usd: budgetUsd });
  const current = useMemo(() => all.data?.items.find((m) => m.id === value), [all.data, value]);
  const overBudget = current?.over_budget;

  return (
    <div>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          className="flex h-9 w-full items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 text-left text-sm hover:border-border-strong"
          aria-label="Model"
        >
          <span className="truncate font-mono text-[13px]">{value.split("/").pop()}</span>
          <span className="flex items-center gap-2 font-mono text-xs text-fg-subtle">
            {current && `${price(current)} per Mtok`}
            <ChevronDown className="h-3.5 w-3.5" />
          </span>
        </PopoverTrigger>
        <PopoverContent className="w-[min(680px,calc(100vw-2rem))] p-0">
          <Command shouldFilter={false} label="Choose a model">
            <div className="flex items-center gap-2 border-b border-border px-3">
              <span className="text-fg-faint">⌕</span>
              <Command.Input
                value={q}
                onValueChange={setQ}
                placeholder="Search models (claude, gpt, deepseek…)"
                className="h-10 flex-1 bg-transparent text-sm outline-none placeholder:text-fg-faint"
              />
              <kbd className="font-mono text-[10.5px] text-fg-faint">esc</kbd>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-3 py-2">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  onClick={() => setFilter(f.key)}
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs",
                    filter === f.key ? "border-accent bg-accent-tint text-accent" : "border-border text-fg-subtle hover:text-fg",
                  )}
                >
                  {f.label}
                </button>
              ))}
              <select
                className="ml-auto bg-transparent text-xs text-fg-subtle"
                value={sort}
                onChange={(e) => setSort(e.target.value as typeof sort)}
                aria-label="Sort models"
              >
                <option value="price">Sort: price</option>
                <option value="context">Sort: context</option>
                <option value="name">Sort: name</option>
              </select>
            </div>
            <div className="grid grid-cols-[1fr_70px_120px_110px] gap-2 px-3 py-1.5 text-[11px] text-fg-faint">
              <span>Model</span>
              <span>Context</span>
              <span>In / out per Mtok</span>
              <span>{data?.basis === "video" ? "This video ≈" : "Per post ≈"}</span>
            </div>
            <Command.List className="max-h-80 overflow-y-auto px-1 pb-1">
              {isFetching && !data && <Command.Loading>Loading models…</Command.Loading>}
              <Command.Empty className="px-3 py-6 text-center text-sm text-fg-subtle">No tool-calling models match.</Command.Empty>
              {data?.items.map((m) => (
                <Command.Item
                  key={m.id}
                  value={m.id}
                  onSelect={() => {
                    onChange(m.id);
                    setOpen(false);
                  }}
                  className="grid cursor-pointer grid-cols-[1fr_70px_120px_110px] items-center gap-2 rounded-md px-2 py-2 text-sm data-[selected=true]:bg-sidebar"
                >
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5 truncate font-mono text-[13px]">
                      {m.id === value && <Check className="h-3.5 w-3.5 text-accent" />}
                      {m.id}
                    </span>
                    <span className="block truncate text-xs text-fg-subtle">
                      {m.provider}
                      {m.is_default && " · your default"}
                      {m.used_before && !m.is_default && " · used before"}
                      {m.over_budget && <span className="text-warning"> · Over your {fmtMoney(budgetUsd)} job budget</span>}
                    </span>
                  </span>
                  <span className="font-mono text-xs text-fg-muted">{ctx(m.context_length)}</span>
                  <span className="font-mono text-xs text-fg-muted">{price(m)}</span>
                  <span className={cn("font-mono text-xs", m.over_budget ? "text-warning" : "text-fg-muted")}>
                    {estimate(m)} {m.over_budget && "⚠"}
                  </span>
                </Command.Item>
              ))}
            </Command.List>
            <div className="flex items-center justify-between border-t border-border px-3 py-2 text-[11px] text-fg-faint">
              <span>
                Prices from OpenRouter, billed to your key{keyLast4 && <span className="font-mono"> …{keyLast4}</span>}
              </span>
              <span>↑↓ move · ↵ select</span>
            </div>
          </Command>
        </PopoverContent>
      </Popover>
      {overBudget && (
        <p className="mt-1.5 flex items-center gap-1.5 text-xs text-warning" role="status">
          <AlertTriangle className="h-3.5 w-3.5" />
          {value.split("/").pop()} may exceed your {fmtMoney(budgetUsd)} budget. Raise it under Advanced or pick a cheaper model.
        </p>
      )}
    </div>
  );
}
