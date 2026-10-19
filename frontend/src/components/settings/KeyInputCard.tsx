"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, FieldError, Input } from "@/components/ui/primitives";
import { ApiError, api, call, type Schemas } from "@/lib/api/client";
import { qk } from "@/lib/hooks/queries";
import { fmtRelative } from "@/lib/utils";

type Provider = "openrouter" | "devto";

const META: Record<Provider, { name: string; blurb: string; help: string; helpUrl: string }> = {
  openrouter: {
    name: "OpenRouter",
    blurb: "Pays for the LLM calls.",
    help: "Where do I get a key?",
    helpUrl: "https://openrouter.ai/settings/keys",
  },
  devto: {
    name: "dev.to",
    blurb: "Publishes to your account. Create one at Settings → Extensions on dev.to.",
    help: "Help",
    helpUrl: "https://dev.to/settings/extensions",
  },
};

export function KeyInputCard({ provider, status }: { provider: Provider; status: Schemas["IntegrationStatus"] }) {
  const qc = useQueryClient();
  const m = META[provider];
  const [editing, setEditing] = useState(!status.connected);
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: qk.integrations });
  };

  const save = useMutation({
    mutationFn: () => call(() => api.PUT("/api/v1/me/integrations/{provider}", { params: { path: { provider } }, body: { api_key: key.trim() } })),
    onSuccess: (data) => {
      qc.setQueryData(qk.integrations, data);
      setKey(""); // the key leaves client state as soon as it's stored
      setEditing(false);
      setError(null);
      toast.success(`${m.name} connected`);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Couldn't save the key."),
  });
  const test = useMutation({
    mutationFn: () => call(() => api.POST("/api/v1/me/integrations/{provider}/test", { params: { path: { provider } } })),
    onSuccess: (r) => {
      refresh();
      if (r.status === "ok") toast.success(`${m.name} key works`);
      else toast.error(`${m.name} rejected the key`);
    },
  });
  const remove = useMutation({
    mutationFn: () => call(() => api.DELETE("/api/v1/me/integrations/{provider}", { params: { path: { provider } } })),
    onSuccess: () => {
      refresh();
      setConfirm(false);
      setEditing(true);
    },
  });

  const statusLine = !status.connected ? (
    <span className="text-fg-subtle">○ Not connected</span>
  ) : status.status === "invalid" ? (
    <span className="text-danger">✕ Invalid key · …{status.last4}</span>
  ) : (
    <span className="text-success">
      ✓ Connected · <span className="font-mono">…{status.last4}</span>
      {status.username && <> · <span className="font-mono">@{status.username}</span></>}
      {status.verified_at && <span className="text-fg-subtle"> · verified {fmtRelative(status.verified_at)}</span>}
    </span>
  );

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{m.name}</h3>
          <p className="mt-0.5 text-sm text-fg-subtle">{m.blurb}</p>
        </div>
        <a href={m.helpUrl} target="_blank" rel="noreferrer" className="text-xs text-accent hover:underline">
          {m.help}
        </a>
      </div>
      <p className="mt-3 text-sm">{statusLine}</p>

      {editing ? (
        <form
          className="mt-4 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (key.trim()) save.mutate();
          }}
        >
          <Input
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="••••••••••••••••••••"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            className="flex-1 font-mono"
            aria-label={`${m.name} API key`}
            invalid={!!error}
          />
          <Button type="submit" variant="primary" loading={save.isPending} disabled={!key.trim()}>
            Save & verify
          </Button>
          {status.connected && (
            <Button type="button" variant="ghost" onClick={() => { setEditing(false); setKey(""); setError(null); }}>
              Cancel
            </Button>
          )}
          <div className="w-full">
            <FieldError>{error}</FieldError>
          </div>
        </form>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={() => setEditing(true)}>Replace key…</Button>
          <Button onClick={() => test.mutate()} loading={test.isPending}>
            Test connection
          </Button>
          <Button variant="danger" onClick={() => setConfirm(true)}>
            Disconnect
          </Button>
        </div>
      )}

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={`Disconnect ${m.name}?`}
        body="The stored key is deleted. New posts are blocked until you connect a key again; running jobs will fail at their next step."
        confirmLabel="Disconnect"
        danger
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </Card>
  );
}
