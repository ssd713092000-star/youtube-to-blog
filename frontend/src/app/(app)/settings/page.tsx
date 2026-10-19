"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog, PageHeader } from "@/components/common";
import { ModelPicker } from "@/components/jobs/ModelPicker";
import { KeyInputCard } from "@/components/settings/KeyInputCard";
import { StyleProfilesPanel } from "@/components/settings/StyleProfiles";
import { Button } from "@/components/ui/button";
import { Slider, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlay";
import { Card, FieldError, Input, Label, Skeleton } from "@/components/ui/primitives";
import { ApiError, api, call, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { useIntegrations, useMe, useModels, useSaveSettings, useSettings, useStyleProfiles } from "@/lib/hooks/queries";
import { cn, fmtMoney } from "@/lib/utils";

const SUGGESTED = [
  ["deepseek/deepseek-v4.1-flash", "Cheapest. Fine for most tutorials."],
  ["anthropic/claude-haiku-4.5", "Better prose, fewer revisions."],
  ["anthropic/claude-sonnet-4.5", "Highest quality, long videos."],
] as const;

function Integrations() {
  const { data } = useIntegrations();
  if (!data) return <Skeleton className="h-64" />;
  return (
    <div className="space-y-4">
      <KeyInputCard provider="openrouter" status={data.openrouter} />
      <KeyInputCard provider="devto" status={data.devto} />
      <p className="text-xs text-fg-subtle">
        Keys are encrypted with Google Cloud KMS and stored separately from your content. They are never shown again after saving.
      </p>
    </div>
  );
}

function Defaults() {
  const settings = useSettings();
  const save = useSaveSettings();
  const profiles = useStyleProfiles();
  const integrations = useIntegrations();
  const models = useModels({});
  const [form, setForm] = useState<Schemas["UserSettings"] | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    if (settings.data && !form) setForm(settings.data);
  }, [settings.data, form]);
  if (!form) return <Skeleton className="h-96" />;
  const set = <K extends keyof Schemas["UserSettings"]>(k: K, v: Schemas["UserSettings"][K]) => setForm({ ...form, [k]: v });
  const perPost = (id: string) => models.data?.items.find((m) => m.id === id)?.estimate_usd;

  return (
    <Card className="space-y-6 p-5">
      <div>
        <Label>Default model</Label>
        <p className="-mt-1 mb-3 text-xs text-fg-subtle">Used for every new post. You can still change it per job.</p>
        <div className="space-y-2" role="radiogroup" aria-label="Suggested models">
          {SUGGESTED.map(([id, blurb]) => {
            const est = perPost(id);
            return (
              <button
                key={id}
                role="radio"
                aria-checked={form.default_model === id}
                onClick={() => set("default_model", id)}
                className={cn("flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left", form.default_model === id ? "border-accent bg-accent-tint/40" : "border-border hover:border-border-strong")}
              >
                <span className={cn("h-3.5 w-3.5 rounded-full border-2", form.default_model === id ? "border-accent bg-accent" : "border-border-strong")} />
                <span className="flex-1">
                  <span className="block font-mono text-[13px]">{id.split("/").pop()}</span>
                  <span className="block text-xs text-fg-subtle">{blurb}</span>
                </span>
                {est && <span className="font-mono text-xs text-fg-subtle">~{fmtMoney((est.low + est.high) / 2, true)} / post</span>}
              </button>
            );
          })}
        </div>
        <div className="mt-3">
          <p className="mb-1.5 text-xs text-fg-subtle">Or browse all OpenRouter models:</p>
          <ModelPicker value={form.default_model} onChange={(id) => set("default_model", id)} budgetUsd={form.default_budget_usd} keyLast4={integrations.data?.openrouter.last4} />
          <FieldError>{errors.default_model}</FieldError>
        </div>
        {models.data && (
          <p className="mt-2 text-xs text-fg-faint">
            Estimates use {models.data.basis === "your_average" ? "your last 30 days of posts" : "a typical 22-minute video"} (~{models.data.basis_words.toLocaleString()} words).
          </p>
        )}
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <Label>Attribution</Label>
          <select className="h-9 w-full rounded-md border border-border bg-surface px-2 text-sm" value={form.default_attribution} onChange={(e) => set("default_attribution", e.target.value as "own_video" | "credited")}>
            <option value="credited">Credit the creator</option>
            <option value="own_video">It's my video</option>
          </select>
        </div>
        <div>
          <Label>Style profile</Label>
          <select className="h-9 w-full rounded-md border border-border bg-surface px-2 text-sm" value={form.default_style_profile_id ?? ""} onChange={(e) => set("default_style_profile_id", e.target.value || null)}>
            <option value="">None</option>
            {profiles.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label>Max auto-revisions</Label>
          <Input type="number" min={0} max={3} value={form.default_max_revisions} onChange={(e) => set("default_max_revisions", Number(e.target.value))} className="font-mono" />
        </div>
        <div>
          <Label>
            Min. faithfulness <span className="ml-1 font-mono text-fg">{form.default_min_faithfulness.toFixed(2)}</span>
          </Label>
          <Slider label="Minimum faithfulness" min={0.5} max={1} step={0.05} value={[form.default_min_faithfulness]} onValueChange={(v) => set("default_min_faithfulness", v[0] ?? 0.85)} />
        </div>
        <div>
          <Label>Budget per job ($)</Label>
          <Input type="number" min={0.01} step={0.05} value={form.default_budget_usd} onChange={(e) => set("default_budget_usd", Number(e.target.value))} className="font-mono" invalid={!!errors.default_budget_usd} />
          <FieldError>{errors.default_budget_usd}</FieldError>
        </div>
        <div>
          <Label>Monthly budget ($)</Label>
          <Input type="number" min={1} step={1} value={form.monthly_budget_usd} onChange={(e) => set("monthly_budget_usd", Number(e.target.value))} className="font-mono" />
        </div>
      </div>

      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="ghost" onClick={() => settings.data && setForm(settings.data)}>
          Cancel
        </Button>
        <Button
          variant="primary"
          loading={save.isPending}
          onClick={() =>
            save.mutate(form, {
              onSuccess: () => {
                setErrors({});
                toast.success("Defaults saved");
              },
              onError: (e) => {
                if (e instanceof ApiError) setErrors(e.fieldErrors);
                toast.error((e as Error).message);
              },
            })
          }
        >
          Save defaults
        </Button>
      </div>
    </Card>
  );
}

function Account() {
  const me = useMe();
  const { signOut } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const del = useMutation({
    mutationFn: (email: string) => call(() => api.DELETE("/api/v1/me", { body: { confirm_email: email } })),
    onSuccess: async () => {
      await signOut();
      router.replace("/login");
    },
    onError: (e) => toast.error((e as Error).message),
  });
  if (!me.data) return <Skeleton className="h-48" />;
  return (
    <div className="space-y-4">
      <Card className="p-5">
        <h3 className="text-sm font-semibold">Profile</h3>
        <dl className="mt-3 grid grid-cols-[100px_1fr] gap-y-2 text-sm">
          <dt className="text-fg-subtle">Name</dt>
          <dd>{me.data.display_name ?? "—"}</dd>
          <dt className="text-fg-subtle">Email</dt>
          <dd>{me.data.email}</dd>
        </dl>
        <Button className="mt-4" onClick={() => void signOut().then(() => router.replace("/login"))}>
          Sign out
        </Button>
      </Card>
      <Card className="border-danger/30 p-5">
        <h3 className="text-sm font-semibold text-danger">Delete account & all data</h3>
        <p className="mt-1 text-sm text-fg-subtle">
          Deletes your jobs, drafts, transcripts, style profiles and stored API keys. Articles already on dev.to stay there.
        </p>
        <Button variant="danger" className="mt-4" onClick={() => setOpen(true)}>
          Delete account…
        </Button>
      </Card>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Delete your account?"
        body="This can't be undone."
        confirmLabel="Delete everything"
        danger
        typedConfirm={me.data.email ?? ""}
        loading={del.isPending}
        onConfirm={() => del.mutate(me.data!.email ?? "")}
      />
    </div>
  );
}

function SettingsTabs() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = params.get("tab") ?? "integrations";
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Settings" />
      <Tabs value={tab} onValueChange={(v) => router.replace(`/settings?tab=${v}`)}>
        <TabsList className="mb-5">
          <TabsTrigger value="integrations">Integrations</TabsTrigger>
          <TabsTrigger value="defaults">Defaults</TabsTrigger>
          <TabsTrigger value="style">Style profiles</TabsTrigger>
          <TabsTrigger value="account">Account</TabsTrigger>
        </TabsList>
        <TabsContent value="integrations">
          <Integrations />
        </TabsContent>
        <TabsContent value="defaults">
          <Defaults />
        </TabsContent>
        <TabsContent value="style">
          <StyleProfilesPanel />
        </TabsContent>
        <TabsContent value="account">
          <Account />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense>
      <SettingsTabs />
    </Suspense>
  );
}
