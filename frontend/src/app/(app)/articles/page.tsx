"use client";

import { ExternalLink, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState, ErrorState, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, Input, Skeleton } from "@/components/ui/primitives";
import { useArticles } from "@/lib/hooks/queries";
import { fmtRelative } from "@/lib/utils";

export default function ArticlesPage() {
  const [q, setQ] = useState("");
  const articles = useArticles(q);
  const rows = articles.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <>
      <PageHeader
        title="Articles"
        actions={
          <div className="relative w-64">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-fg-faint" />
            <Input className="pl-8" placeholder="Search titles…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search articles" />
          </div>
        }
      />
      {articles.isError ? (
        <ErrorState error={articles.error} onRetry={() => void articles.refetch()} />
      ) : articles.isLoading ? (
        <Skeleton className="h-64" />
      ) : rows.length === 0 ? (
        <EmptyState title={q ? "No articles match" : "Nothing published yet"} body={q ? undefined : "Approved posts show up here once they reach dev.to."} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((a) => (
            <Card key={`${a.video_id}-${a.devto_url}`} className="overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={a.thumbnail_url || "/placeholder.svg"} alt="" className="aspect-video w-full object-cover" loading="lazy" />
              <div className="p-4">
                <div className="flex items-center gap-2">
                  <span className={a.publish_status === "published" ? "rounded bg-success-bg px-1.5 py-px text-[11px] text-success" : "rounded bg-sidebar px-1.5 py-px text-[11px] text-fg-muted"}>
                    {a.publish_status === "published" ? "Public" : "Draft"}
                  </span>
                  <span className="text-xs text-fg-subtle">{fmtRelative(a.published_at)}</span>
                </div>
                <h3 className="mt-2 line-clamp-2 text-sm font-semibold">{a.title}</h3>
                <div className="mt-3 flex flex-wrap gap-3 text-xs">
                  <a href={a.devto_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                    dev.to <ExternalLink className="h-3 w-3" />
                  </a>
                  <a href={`https://www.youtube.com/watch?v=${a.video_id}`} target="_blank" rel="noreferrer" className="text-fg-subtle hover:text-fg">
                    Video
                  </a>
                  {a.job_id && (
                    <Link href={`/jobs/${a.job_id}/result`} className="text-fg-subtle hover:text-fg">
                      Job
                    </Link>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
      {articles.hasNextPage && (
        <div className="mt-5 text-center">
          <Button loading={articles.isFetchingNextPage} onClick={() => void articles.fetchNextPage()}>
            Load more
          </Button>
        </div>
      )}
    </>
  );
}
