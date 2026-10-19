"use client";

import { BarChart3, FileText, LayoutDashboard, LogOut, Moon, Palette, Plus, Settings, Sun, WifiOff } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownSeparator, DropdownTrigger, Tooltip } from "@/components/ui/overlay";
import { useApiReachable } from "@/lib/api/health";
import { useAuth } from "@/lib/auth";
import { useDashboard, useKeysConnected } from "@/lib/hooks/queries";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, badge: true },
  { href: "/jobs/new", label: "New post", icon: Plus },
  { href: "/articles", label: "Articles", icon: FileText },
  { href: "/settings/style-profiles", label: "Style profiles", icon: Palette },
  { href: "/usage", label: "Usage", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const path = usePathname();
  const { data: dash } = useDashboard();
  const { user, signOut } = useAuth();
  const router = useRouter();
  const active = (href: string) =>
    href === "/settings" ? path === "/settings" : path === href || (href !== "/jobs/new" && path.startsWith(href + "/"));

  return (
    <aside className="hidden w-[216px] shrink-0 flex-col border-r border-border bg-sidebar px-2.5 py-3.5 md:flex">
      <Link href="/dashboard" className="flex items-center gap-2 px-2 pb-5 pt-1">
        <span className="grid h-[22px] w-[22px] place-items-center rounded-md bg-fg font-mono text-[11px] font-semibold text-bg">t2</span>
        <span className="text-sm font-semibold tracking-tight">Tube2Dev</span>
      </Link>
      <nav className="flex flex-col gap-0.5" aria-label="Main">
        {NAV.map((n) => (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active(n.href) ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px]",
              active(n.href) ? "bg-surface font-medium text-fg shadow-sm" : "text-fg-muted hover:bg-surface/60 hover:text-fg",
            )}
          >
            <n.icon className="h-3.5 w-3.5 opacity-70" aria-hidden />
            <span className="flex-1">{n.label}</span>
            {n.badge && dash && dash.awaiting_you > 0 && (
              <span className="rounded-full bg-accent px-1.5 py-px font-mono text-[11px] text-white" aria-label={`${dash.awaiting_you} waiting`}>
                {dash.awaiting_you}
              </span>
            )}
          </Link>
        ))}
      </nav>
      <div className="flex-1" />
      <DropdownMenu>
        <DropdownTrigger className="flex items-center gap-2 rounded-md p-2 text-left hover:bg-surface/60">
          <Avatar name={user?.displayName ?? user?.email ?? "?"} src={user?.photoURL} />
          <span className="min-w-0 flex-1 truncate text-xs text-fg-muted">{user?.email}</span>
        </DropdownTrigger>
        <DropdownContent align="start" side="top">
          <DropdownItem onSelect={() => router.push("/settings?tab=account")}>Account</DropdownItem>
          <DropdownItem onSelect={() => router.push("/settings")}>Settings</DropdownItem>
          <DropdownSeparator />
          <DropdownItem onSelect={() => void signOut().then(() => router.replace("/login"))}>
            <LogOut className="h-3.5 w-3.5" /> Sign out
          </DropdownItem>
        </DropdownContent>
      </DropdownMenu>
    </aside>
  );
}

function Avatar({ name, src }: { name: string; src?: string | null }) {
  if (src) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src} alt="" className="h-6 w-6 rounded-full" referrerPolicy="no-referrer" />;
  }
  return (
    <span className="grid h-6 w-6 place-items-center rounded-full bg-accent-tint font-mono text-[11px] text-accent">
      {name.slice(0, 1).toUpperCase()}
    </span>
  );
}

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const dark = mounted && resolvedTheme === "dark";
  return (
    <Button variant="ghost" size="icon" aria-label="Toggle theme" onClick={() => setTheme(dark ? "light" : "dark")}>
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}

export function NewPostButton({ size = "md" }: { size?: "sm" | "md" }) {
  const { ready, loading } = useKeysConnected();
  const btn = (
    <Button variant="primary" size={size} disabled>
      <Plus className="h-3.5 w-3.5" /> New post
    </Button>
  );
  if (ready || loading) {
    return (
      <Link href="/jobs/new" className="inline-flex">
        <Button variant="primary" size={size}>
          <Plus className="h-3.5 w-3.5" /> New post
        </Button>
      </Link>
    );
  }
  return (
    <Tooltip content="Connect your OpenRouter and dev.to keys first">
      <span tabIndex={0}>{btn}</span>
    </Tooltip>
  );
}

export function OnboardingBanner() {
  const { ready, missing, loading } = useKeysConnected();
  if (ready || loading) return null;
  const names = missing.map((m) => (m === "devto" ? "dev.to" : "OpenRouter"));
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-warning/30 bg-warning-bg px-6 py-2.5 text-sm text-warning-strong" role="status">
      <span className="h-2 w-2 rounded-full bg-warning" aria-hidden />
      <span className="font-medium">Connect your API keys to start converting videos.</span>
      <span className="rounded border border-warning/30 px-1.5 py-px text-xs">{names.join(" + ")} key missing</span>
      <Link href="/settings" className="ml-auto text-xs font-medium underline underline-offset-2">
        Go to Integrations →
      </Link>
    </div>
  );
}

export function OfflineBanner() {
  const apiUp = useApiReachable();
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const on = () => setOffline(false);
    const off = () => setOffline(true);
    setOffline(!navigator.onLine);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  if (offline) {
    return (
      <div className="flex items-center gap-2 bg-fg px-6 py-2 text-sm text-bg" role="status">
        <WifiOff className="h-4 w-4" /> You're offline. Changes will sync when you reconnect.
      </div>
    );
  }
  if (!apiUp) {
    return (
      <div className="flex items-center gap-2 bg-fg px-6 py-2 text-sm text-bg" role="status" aria-live="polite">
        <WifiOff className="h-4 w-4" /> Can't reach the Tube2Dev server. Retrying… Jobs keep their progress and resume when it's back.
      </div>
    );
  }
  return null;
}

export function MobileNav() {
  const path = usePathname();
  return (
    <nav className="flex gap-1 overflow-x-auto border-b border-border bg-sidebar px-3 py-2 md:hidden" aria-label="Main">
      {NAV.map((n) => (
        <Link
          key={n.href}
          href={n.href}
          className={cn(
            "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1 text-xs",
            path.startsWith(n.href) ? "bg-surface font-medium text-fg" : "text-fg-muted",
          )}
        >
          <n.icon className="h-3.5 w-3.5" aria-hidden />
          {n.label}
        </Link>
      ))}
    </nav>
  );
}
