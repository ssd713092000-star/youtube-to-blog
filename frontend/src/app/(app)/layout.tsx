"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { MobileNav, OfflineBanner, OnboardingBanner, Sidebar } from "@/components/shell";
import { Skeleton } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div className="flex h-screen">
        <div className="hidden w-[216px] border-r border-border bg-sidebar md:block" />
        <div className="flex-1 space-y-4 p-8">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <OfflineBanner />
        <MobileNav />
        <OnboardingBanner />
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-8">{children}</main>
      </div>
    </div>
  );
}
