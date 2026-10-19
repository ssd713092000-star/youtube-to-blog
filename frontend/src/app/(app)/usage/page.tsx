"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ErrorState, PageHeader } from "@/components/common";
import { Card, Skeleton } from "@/components/ui/primitives";
import { useUsage } from "@/lib/hooks/queries";
import { cn, fmtMoney, fmtTokens } from "@/lib/utils";

const PERIODS = ["7d", "30d", "90d"] as const;

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <Card className="px-4 py-3">
      <div className="text-xs text-fg-subtle">{label}</div>
      <div className="mt-1 font-mono text-xl font-semibold">{value}</div>
    </Card>
  );
}

export default function UsagePage() {
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("30d");
  const usage = useUsage(period);
  const u = usage.data;

  return (
    <>
      <PageHeader
        title="Usage"
        actions={
          <div role="tablist" aria-label="Period" className="flex gap-1 rounded-lg bg-sidebar p-1">
            {PERIODS.map((p) => (
              <button key={p} role="tab" aria-selected={period === p} onClick={() => setPeriod(p)} className={cn("rounded-md px-3 py-1 text-xs font-medium", period === p ? "bg-surface shadow-sm" : "text-fg-subtle")}>
                {p}
              </button>
            ))}
          </div>
        }
      />
      {usage.isError ? (
        <ErrorState error={usage.error} onRetry={() => void usage.refetch()} />
      ) : !u ? (
        <Skeleton className="h-96" />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi label="Jobs" value={String(u.jobs)} />
            <Kpi label="Cost" value={fmtMoney(u.cost_usd, true)} />
            <Kpi label="Tokens" value={fmtTokens(u.tokens)} />
            <Kpi label="Avg. cost / post" value={fmtMoney(u.avg_cost_per_post, true)} />
          </div>

          <Card className="p-4">
            <h2 className="mb-3 text-sm font-semibold">Daily cost</h2>
            <div className="h-64" role="img" aria-label={`Daily LLM cost over the last ${period}`}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={u.daily} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} tick={{ fontSize: 11, fill: "var(--fg-subtle)" }} tickLine={false} axisLine={false} minTickGap={16} />
                  <YAxis tickFormatter={(v: number) => `$${v.toFixed(2)}`} tick={{ fontSize: 11, fill: "var(--fg-subtle)" }} tickLine={false} axisLine={false} width={52} />
                  <Tooltip
                    cursor={{ fill: "var(--sidebar)" }}
                    contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => [fmtMoney(v, true), "Cost"]}
                  />
                  <Bar dataKey="cost_usd" fill="var(--accent)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
            <Card className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-fg-subtle">
                    <th className="px-4 py-2.5 font-medium">Model</th>
                    <th className="px-3 py-2.5 font-medium">Jobs</th>
                    <th className="px-3 py-2.5 font-medium">Tokens</th>
                    <th className="px-3 py-2.5 font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {u.by_model.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-4 py-6 text-center text-fg-subtle">
                        No usage in this period.
                      </td>
                    </tr>
                  )}
                  {u.by_model.map((m) => (
                    <tr key={m.model} className="border-b border-border last:border-0">
                      <td className="px-4 py-2.5 font-mono text-xs">{m.model}</td>
                      <td className="px-3 py-2.5 font-mono text-xs">{m.jobs}</td>
                      <td className="px-3 py-2.5 font-mono text-xs">{fmtTokens(m.tokens)}</td>
                      <td className="px-3 py-2.5 font-mono text-xs">{fmtMoney(m.cost_usd, true)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card className="p-4">
              <h2 className="text-sm font-semibold">Daily job quota</h2>
              <p className="mt-1 font-mono text-lg">
                {u.quota.used_today} / {u.quota.jobs_per_day}
              </p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border" role="meter" aria-valuemin={0} aria-valuemax={u.quota.jobs_per_day} aria-valuenow={u.quota.used_today} aria-label="Jobs used today">
                <div className="h-full bg-accent" style={{ width: `${Math.min(100, (u.quota.used_today / u.quota.jobs_per_day) * 100)}%` }} />
              </div>
              <p className="mt-2 text-xs text-fg-subtle">Resets at midnight UTC.</p>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
