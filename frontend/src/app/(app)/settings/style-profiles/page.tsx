"use client";

import { PageHeader } from "@/components/common";
import { StyleProfilesPanel } from "@/components/settings/StyleProfiles";

export default function StyleProfilesPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader crumbs={[{ label: "Settings", href: "/settings" }, { label: "Style profiles" }]} title="Style profiles" />
      <StyleProfilesPanel />
    </div>
  );
}
