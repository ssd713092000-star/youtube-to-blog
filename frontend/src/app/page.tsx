"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

const STEPS = [
  ["Paste a YouTube link", "We pull the transcript and chapters, and tell you up front if a video can't be converted."],
  ["Review the draft", "Every claim is fact-checked against the transcript. Edit, request a revision, or approve."],
  ["Approve the publish", "It lands as a private dev.to draft by default. Nothing goes public without you."],
];

export default function Landing() {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [loading, user, router]);

  return (
    <div className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-16">
      <div className="flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-fg font-mono text-xs font-semibold text-bg">t2</span>
        <span className="font-semibold">Tube2Dev</span>
      </div>
      <h1 className="mt-10 text-4xl font-semibold tracking-tight">Turn YouTube videos into dev.to posts.</h1>
      <p className="mt-3 text-lg text-fg-subtle">An AI pipeline writes the draft. You review every word before it goes out.</p>
      <ol className="mt-10 grid gap-4 sm:grid-cols-3">
        {STEPS.map(([t, d], i) => (
          <li key={t} className="rounded-[10px] border border-border bg-surface p-4">
            <span className="font-mono text-xs text-accent">0{i + 1}</span>
            <h2 className="mt-2 text-sm font-semibold">{t}</h2>
            <p className="mt-1 text-sm text-fg-subtle">{d}</p>
          </li>
        ))}
      </ol>
      <div className="mt-10">
        <Link href="/login">
          <Button variant="primary" size="lg">
            Sign in
          </Button>
        </Link>
      </div>
    </div>
  );
}
