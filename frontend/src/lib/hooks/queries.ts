"use client";

import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call, type Schemas } from "@/lib/api/client";

export const qk = {
  me: ["me"] as const,
  settings: ["settings"] as const,
  integrations: ["integrations"] as const,
  dashboard: ["dashboard"] as const,
  usage: (period: string) => ["usage", period] as const,
  jobs: (status: string, q: string) => ["jobs", status, q] as const,
  job: (id: string) => ["job", id] as const,
  drafts: (id: string) => ["drafts", id] as const,
  draft: (id: string, rev: number) => ["draft", id, rev] as const,
  outline: (id: string) => ["outline", id] as const,
  factCheck: (id: string) => ["fact-check", id] as const,
  review: (id: string) => ["review", id] as const,
  publishRequest: (id: string) => ["publish-request", id] as const,
  result: (id: string) => ["result", id] as const,
  articles: (q: string) => ["articles", q] as const,
  styleProfiles: ["style-profiles"] as const,
  models: (params: object) => ["models", params] as const,
};

export const ACTIVE_STATUSES = new Set(["queued", "running", "publishing"]);

export function useMe() {
  return useQuery({ queryKey: qk.me, queryFn: () => call(() => api.GET("/api/v1/me")) });
}

export function useSettings() {
  return useQuery({ queryKey: qk.settings, queryFn: () => call(() => api.GET("/api/v1/me/settings")) });
}

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["UserSettings"]) => call(() => api.PUT("/api/v1/me/settings", { body })),
    onSuccess: (data) => {
      qc.setQueryData(qk.settings, data);
      void qc.invalidateQueries({ queryKey: qk.me });
    },
  });
}

export function useIntegrations() {
  return useQuery({ queryKey: qk.integrations, queryFn: () => call(() => api.GET("/api/v1/me/integrations")) });
}

export function useKeysConnected(): { ready: boolean; missing: ("openrouter" | "devto")[]; loading: boolean } {
  const { data, isLoading } = useIntegrations();
  if (!data) return { ready: false, missing: [], loading: isLoading };
  const missing = (["openrouter", "devto"] as const).filter((p) => !data[p].connected || data[p].status === "invalid");
  return { ready: missing.length === 0, missing: [...missing], loading: false };
}

export function useDashboard() {
  return useQuery({ queryKey: qk.dashboard, queryFn: () => call(() => api.GET("/api/v1/me/dashboard")), refetchInterval: 30_000 });
}

export function useUsage(period: "7d" | "30d" | "90d") {
  return useQuery({
    queryKey: qk.usage(period),
    queryFn: () => call(() => api.GET("/api/v1/me/usage", { params: { query: { period } } })),
  });
}

export function useJobs(status: string, q: string) {
  return useInfiniteQuery({
    queryKey: qk.jobs(status, q),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET("/api/v1/jobs", {
          params: { query: { status: status === "all" ? undefined : status, q: q || undefined, cursor: pageParam ?? undefined, limit: 25 } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
    placeholderData: keepPreviousData,
    // Live rows (running jobs) refresh while the dashboard is open.
    refetchInterval: (query) =>
      query.state.data?.pages.some((p) => p.items.some((j) => ACTIVE_STATUSES.has(j.status))) ? 5000 : 30_000,
  });
}

export function useJob(id: string) {
  return useQuery({
    queryKey: qk.job(id),
    queryFn: () => call(() => api.GET("/api/v1/jobs/{job_id}", { params: { path: { job_id: id } } })),
  });
}

export function useDrafts(id: string, enabled = true) {
  return useQuery({
    queryKey: qk.drafts(id),
    enabled,
    queryFn: () => call(() => api.GET("/api/v1/jobs/{job_id}/drafts", { params: { path: { job_id: id } } })),
  });
}

export function useDraft(id: string, rev: number | null | undefined) {
  return useQuery({
    queryKey: qk.draft(id, rev ?? -1),
    enabled: rev != null,
    staleTime: Infinity, // draft versions are immutable
    queryFn: () =>
      call(() => api.GET("/api/v1/jobs/{job_id}/drafts/{rev}", { params: { path: { job_id: id, rev: rev as number } } })),
  });
}

export function useOutline(id: string, enabled = true) {
  return useQuery({
    queryKey: qk.outline(id),
    enabled,
    queryFn: () => call(() => api.GET("/api/v1/jobs/{job_id}/outline", { params: { path: { job_id: id } } })),
  });
}

export function useFactCheck(id: string, enabled = true) {
  return useQuery({
    queryKey: qk.factCheck(id),
    enabled,
    queryFn: () => call(() => api.GET("/api/v1/jobs/{job_id}/fact-check", { params: { path: { job_id: id } } })),
  });
}

export function useReview(id: string, enabled = true) {
  return useQuery({
    queryKey: qk.review(id),
    enabled,
    retry: false,
    queryFn: () => call(() => api.GET("/api/v1/jobs/{job_id}/review", { params: { path: { job_id: id } } })),
  });
}

export function usePublishRequest(id: string, enabled = true) {
  return useQuery({
    queryKey: qk.publishRequest(id),
    enabled,
    retry: false,
    queryFn: () => call(() => api.GET("/api/v1/jobs/{job_id}/publish-request", { params: { path: { job_id: id } } })),
  });
}

export function useResult(id: string, enabled = true) {
  return useQuery({
    queryKey: qk.result(id),
    enabled,
    queryFn: () => call(() => api.GET("/api/v1/jobs/{job_id}/result", { params: { path: { job_id: id } } })),
  });
}

export function useArticles(q: string) {
  return useInfiniteQuery({
    queryKey: qk.articles(q),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(() => api.GET("/api/v1/articles", { params: { query: { q: q || undefined, cursor: pageParam ?? undefined } } })),
    getNextPageParam: (last) => last.next_cursor ?? null,
  });
}

export function useStyleProfiles() {
  return useQuery({ queryKey: qk.styleProfiles, queryFn: () => call(() => api.GET("/api/v1/style-profiles")) });
}

export interface ModelQuery {
  q?: string;
  max_price_mtok?: number;
  min_context?: number;
  used_before?: boolean;
  sort?: "price" | "context" | "name";
  video_id?: string;
  budget_usd?: number;
}

export function useModels(params: ModelQuery, enabled = true) {
  return useQuery({
    queryKey: qk.models(params),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
    queryFn: () => call(() => api.GET("/api/v1/models", { params: { query: { ...params, limit: 200 } } })),
  });
}
