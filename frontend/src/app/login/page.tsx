"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import { config } from "@/lib/config";
import { logger } from "@/lib/logger";

const DEMO_LINES = [
  ["00:12", "so the first thing you want is a cargo project"],
  ["00:31", "clap gives you a derive api for arguments"],
  ["02:41", "um, let me add a subcommand here real quick"],
  ["06:12", "and anyhow just wraps any error type"],
  ["07:04", "it keeps the code way shorter honestly"],
];
const DEMO_STEPS = ["Clean transcript", "Plan outline", "Write sections", "Fact-check"];

function LoginDemo() {
  return (
    <div className="hidden w-[480px] flex-col gap-3.5 lg:flex" aria-hidden>
      <div className="relative overflow-hidden rounded-[10px] border border-border bg-surface p-3.5">
        <div className="mb-2 font-mono text-[11px] text-fg-subtle">transcript.vtt</div>
        <div className="pointer-events-none absolute inset-x-2 top-[30px] h-[26px] animate-[t2d-scan_6s_ease-in-out_infinite] rounded bg-accent/10 shadow-[inset_2px_0_0_var(--accent)]" />
        {DEMO_LINES.map(([t, s]) => (
          <div key={t} className="relative flex gap-2.5 truncate font-mono text-xs leading-[26px] text-fg-muted">
            <span className="text-fg-faint">{t}</span>
            {s}
          </div>
        ))}
      </div>
      <div className="flex justify-center gap-1.5">
        {DEMO_STEPS.map((s, i) => (
          <span
            key={s}
            className="rounded border border-border bg-surface px-2 py-0.5 font-mono text-[11px] text-accent opacity-40"
            style={{ animation: `t2d-step 6s ${i * 0.9}s ease-in-out infinite` }}
          >
            {s}
          </span>
        ))}
      </div>
      <div className="space-y-2 rounded-[10px] border border-border bg-surface p-3.5">
        {[60, 92, 84, 70, 100, 76, 48].map((w, i) => (
          <div
            key={i}
            className={i === 0 ? "h-3.5 rounded bg-accent" : i === 4 ? "h-7 rounded bg-fg" : "h-2 rounded bg-border-strong"}
            style={{ width: `${w}%`, transformOrigin: "left", animation: `t2d-grow 6s ${0.4 + i * 0.15}s ease-out infinite` }}
          />
        ))}
      </div>
      <style>{`
        @keyframes t2d-scan{0%,12%{transform:translateY(0)}20%,32%{transform:translateY(26px)}40%,52%{transform:translateY(52px)}60%,72%{transform:translateY(78px)}80%,92%{transform:translateY(104px)}100%{transform:translateY(0)}}
        @keyframes t2d-step{0%,100%{opacity:.35;transform:none}8%,22%{opacity:1;transform:translateX(3px)}30%{opacity:.35;transform:none}}
        @keyframes t2d-grow{0%,8%{transform:scaleX(0)}40%,85%{transform:scaleX(1)}100%{transform:scaleX(1);opacity:0}}
      `}</style>
    </div>
  );
}

function LoginForm() {
  const { user, loading, signInWithGoogle, sendEmailLink, completeEmailLink, signInDev } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/dashboard";
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState<"google" | "email" | null>(null);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    void completeEmailLink().catch((e) => {
      logger.error("email link sign-in failed", e);
      toast.error("That sign-in link is invalid or expired.");
    });
  }, [completeEmailLink]);

  useEffect(() => {
    if (!loading && user) router.replace(next.startsWith("/") ? next : "/dashboard");
  }, [loading, user, router, next]);

  const google = async () => {
    setBusy("google");
    try {
      await signInWithGoogle();
    } catch (e) {
      logger.warn("google sign-in failed", { error: String(e) });
      toast.error("Google sign-in didn't complete.");
    } finally {
      setBusy(null);
    }
  };

  const emailLink = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!email.includes("@")) return;
    if (config.authMode === "dev") {
      signInDev(email.trim().toLowerCase());
      return;
    }
    setBusy("email");
    try {
      await sendEmailLink(email.trim());
      setSent(true);
    } catch (e) {
      logger.warn("email link send failed", { error: String(e) });
      toast.error("Couldn't send the sign-in link.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="w-full max-w-sm">
      <div className="mb-7 flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-fg font-mono text-xs font-semibold text-bg">t2</span>
        <span className="text-base font-semibold">Tube2Dev</span>
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">Sign in to Tube2Dev</h1>
      <p className="mt-2 text-sm text-fg-subtle">Turn YouTube videos into dev.to posts, and review every word before it goes out.</p>

      {config.authMode === "firebase" && (
        <>
          <Button variant="outline" size="lg" className="mt-7 w-full justify-center" onClick={google} loading={busy === "google"}>
            <GoogleIcon /> Continue with Google
          </Button>
          <div className="my-5 flex items-center gap-3 text-xs text-fg-faint">
            <span className="h-px flex-1 bg-border" />
            or
            <span className="h-px flex-1 bg-border" />
          </div>
        </>
      )}

      {sent ? (
        <div className="mt-6 rounded-lg border border-success/30 bg-success-tint px-4 py-3 text-sm text-success" role="status">
          Check {email} for a sign-in link.
        </div>
      ) : (
        <form onSubmit={emailLink} className={config.authMode === "dev" ? "mt-7" : ""}>
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" required autoComplete="email" placeholder="you@company.dev" value={email} onChange={(e) => setEmail(e.target.value)} />
          <Button type="submit" variant="secondary" size="lg" className="mt-3 w-full justify-center" loading={busy === "email"}>
            {config.authMode === "dev" ? "Sign in (local dev)" : "Email me a sign-in link"}
          </Button>
        </form>
      )}

      <p className="mt-6 text-xs leading-relaxed text-fg-subtle">
        Your API keys are encrypted and never shown again. Nothing is published without your approval.
      </p>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden>
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.4h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.2-2.1 3.5-5.1 3.5-8.7z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24z" />
      <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6h-4a12 12 0 0 0 0 10.8l4-3.1z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9z" />
    </svg>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center gap-20 px-6">
      <Suspense>
        <LoginForm />
      </Suspense>
      <LoginDemo />
    </div>
  );
}
