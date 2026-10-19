"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog, EmptyState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, Switch } from "@/components/ui/overlay";
import { Card, FieldError, Input, Label, Skeleton, Textarea } from "@/components/ui/primitives";
import { ApiError, api, call, type Schemas } from "@/lib/api/client";
import { qk, useStyleProfiles } from "@/lib/hooks/queries";
import { fmtRelative } from "@/lib/utils";

type Profile = Schemas["StyleProfileOut"];

function ProfileDialog({ open, onOpenChange, profile }: { open: boolean; onOpenChange: (v: boolean) => void; profile: Profile | null }) {
  const qc = useQueryClient();
  const [name, setName] = useState(profile?.name ?? "");
  const [examples, setExamples] = useState<string[]>(profile?.examples ?? [""]);
  const [isDefault, setIsDefault] = useState(profile?.is_default ?? false);
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), examples: examples.map((e) => e.trim()).filter(Boolean), is_default: isDefault };
      return profile
        ? call(() => api.PUT("/api/v1/style-profiles/{profile_id}", { params: { path: { profile_id: profile.id } }, body }))
        : call(() => api.POST("/api/v1/style-profiles", { body }));
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.styleProfiles });
      void qc.invalidateQueries({ queryKey: qk.settings });
      toast.success("Style profile saved");
      onOpenChange(false);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Couldn't save."),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={profile ? "Edit style profile" : "New style profile"} description="Paste 1–3 of your past posts so new drafts match your voice." side="right">
        <div className="space-y-4">
          <div>
            <Label htmlFor="sp-name">Name</Label>
            <Input id="sp-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="Conversational tutorial" />
          </div>
          {examples.map((ex, i) => (
            <div key={i}>
              <Label className="flex justify-between">
                Example post {i + 1}
                <span className="font-mono text-fg-faint">{ex.split(/\s+/).filter(Boolean).length} words</span>
              </Label>
              <Textarea rows={8} value={ex} onChange={(e) => setExamples(examples.map((x, j) => (j === i ? e.target.value : x)))} className="font-mono text-xs" placeholder="Paste markdown…" />
              {examples.length > 1 && (
                <button className="mt-1 text-xs text-fg-subtle hover:text-danger" onClick={() => setExamples(examples.filter((_, j) => j !== i))}>
                  Remove
                </button>
              )}
            </div>
          ))}
          <div className="flex items-center gap-3">
            {examples.length < 3 && (
              <Button size="sm" onClick={() => setExamples([...examples, ""])}>
                <Plus className="h-3.5 w-3.5" /> Add example
              </Button>
            )}
            <Button size="sm" disabled title="Coming soon">
              Paste from dev.to URL
            </Button>
          </div>
          <label className="flex items-center gap-3 text-sm">
            <Switch checked={isDefault} onCheckedChange={setIsDefault} /> Use as default for new posts
          </label>
          <FieldError>{error}</FieldError>
          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="primary" loading={save.isPending} disabled={!name.trim() || !examples.some((e) => e.trim())} onClick={() => save.mutate()}>
              Save
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function StyleProfilesPanel() {
  const qc = useQueryClient();
  const profiles = useStyleProfiles();
  const [editing, setEditing] = useState<Profile | null | "new">(null);
  const [deleting, setDeleting] = useState<Profile | null>(null);
  const del = useMutation({
    mutationFn: (p: Profile) => call(() => api.DELETE("/api/v1/style-profiles/{profile_id}", { params: { path: { profile_id: p.id } } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.styleProfiles });
      setDeleting(null);
    },
  });

  if (!profiles.data) return <Skeleton className="h-48" />;
  return (
    <div>
      <div className="mb-4 flex justify-end">
        <Button variant="primary" onClick={() => setEditing("new")}>
          <Plus className="h-3.5 w-3.5" /> New profile
        </Button>
      </div>
      {profiles.data.length === 0 ? (
        <EmptyState title="No style profiles yet" body="A style profile teaches the writer your voice using a few of your own posts." />
      ) : (
        <div className="space-y-2">
          {profiles.data.map((p) => (
            <Card key={p.id} className="flex items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm font-medium">
                  {p.name}
                  {p.is_default && <span className="rounded bg-accent-tint px-1.5 py-px text-[11px] text-accent">Default</span>}
                </div>
                <div className="text-xs text-fg-subtle">
                  {p.examples.length} example{p.examples.length !== 1 && "s"} · updated {fmtRelative(p.updated_at)}
                </div>
              </div>
              <Button size="sm" onClick={() => setEditing(p)}>
                Edit
              </Button>
              <Button size="sm" variant="danger" onClick={() => setDeleting(p)}>
                Delete
              </Button>
            </Card>
          ))}
        </div>
      )}
      {editing && <ProfileDialog open onOpenChange={(v) => !v && setEditing(null)} profile={editing === "new" ? null : editing} />}
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(v) => !v && setDeleting(null)}
        title={`Delete "${deleting?.name}"?`}
        body="Jobs already using it keep their drafts; new posts won't use this voice."
        confirmLabel="Delete"
        danger
        loading={del.isPending}
        onConfirm={() => deleting && del.mutate(deleting)}
      />
    </div>
  );
}
