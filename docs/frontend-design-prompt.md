# Frontend design prompt — Tube2Dev

Paste everything below the line into your design/UI generator (v0, Lovable, Claude, Bolt, …).

---

## 1. Product

Build the complete frontend for **Tube2Dev**, a multi-user web app that turns a YouTube video into a dev.to blog post. An AI pipeline runs in the background: it downloads the transcript, cleans it, plans an outline, writes the sections in parallel, assembles the post, fact-checks it against the transcript (and revises it automatically when the score is low), then generates metadata. The pipeline **pauses twice for a human**:

1. **Draft review**: the user reads and edits the draft, then approves it, asks for a revision with feedback, or aborts.
2. **Publish approval**: the user confirms the final dev.to call, choosing between a private draft and a public post, or rejects it.

After publishing, the app generates LinkedIn and X posts.

Each user brings their **own OpenRouter API key** (pays for the LLM) and their **own dev.to API key** (publishes to their account). A user can't start a job until both keys are connected. The keys are write-only: once saved, the UI never shows them again, only a "connected" status.

Users: individual developers and developer advocates who repurpose videos into written posts. They're technical and want speed, transparency about what the AI did, and full control before anything goes public.

Design tone: a calm, precise developer tool, in the vein of Linear, Vercel and Raycast. Use plenty of whitespace and a neutral palette with one accent colour, plus monospace for timestamps, tags and IDs. No stock illustrations and no gradients-everywhere marketing look. Information density matters most on the review screen.

## 2. Tech stack (must use)

- **Next.js 15, App Router, TypeScript (strict)**, React Server Components where sensible; client components for interactive pieces.
- **Tailwind CSS + shadcn/ui** (Radix primitives). Icons: lucide-react.
- **TanStack Query v5** for all server state; query keys per resource (`['jobs', filters]`, `['job', id]`, `['draft', id, rev]`, …).
- **Typed API client** generated from the backend OpenAPI spec with `openapi-typescript` + `openapi-fetch`. Put it in `lib/api/`. Until the backend exists, use a **mock layer** (MSW) that implements every endpoint below with realistic fixtures, including the paused states and errors, so every page can be demoed.
- **Server-Sent Events** for live job progress (`EventSource` wrapper hook `useJobEvents(jobId)` that reconnects with backoff and resumes from `Last-Event-ID`).
- **Auth: Firebase Authentication (Google Identity Platform), "Sign in with Google" + email link.** Every API call sends `Authorization: Bearer <Firebase ID token>`, refreshed automatically. Keep the auth provider behind a small `lib/auth` interface so it can be swapped.
- Markdown editing: **CodeMirror 6** (`@uiw/react-codemirror`, markdown mode). Preview: `react-markdown` + `remark-gfm` + `rehype-highlight`, styled to resemble dev.to's article rendering. Diff view: `react-diff-viewer-continued` or a CodeMirror merge view.
- Forms: `react-hook-form` + `zod`. Toasts: `sonner`. Dates: `date-fns`.
- Dark and light theme (`next-themes`), system default.
- Fully responsive down to 360px wide. The three-column review screen collapses to tabs on tablet and mobile.

## 3. Layout and navigation

- Authenticated app shell with a **collapsible left sidebar**: Dashboard, New post, Articles, Style profiles, Usage, Settings. Show a numeric badge on Dashboard when jobs are waiting for review.
- Top bar: breadcrumbs, a global "New post" button, theme toggle, user avatar menu (profile, settings, sign out).
- A **global onboarding banner** appears when the OpenRouter or dev.to key is missing: "Connect your API keys to start converting videos", linking to Settings → Integrations. While it shows, every "New post" entry point is disabled and has a tooltip explaining why.
- Public pages (no shell): `/` (minimal landing with one sentence, a three-step explainer, and a "Sign in" button), `/login`.

## 4. Backend contract (build the mocks and types to match)

All routes are under `/api/v1`. Errors use the shape `{ error: { code: string, message: string, details?: object } }`. Handle these statuses globally:
- `401`: refresh the token, retry once, then redirect to `/login`.
- `402 / code=budget_exceeded`: the job hit its token budget. Show the cost so far and a "raise budget & retry" action.
- `409`: stale or conflicting action (see Resume rules). Refetch and show a toast: "This job changed since you loaded it."
- `412 / code=keys_missing`: send the user to Integrations.
- `422`: validation errors mapped onto form fields.
- `429`: rate limited. Show the retry-after countdown.
- `5xx`: a toast with a retry button and a copyable request ID (from the `X-Request-ID` header).

### Types

```ts
type JobStatus =
  | 'queued' | 'running' | 'awaiting_review' | 'awaiting_publish'
  | 'publishing' | 'completed' | 'rejected' | 'failed' | 'cancelled';

type PipelineStep =
  | 'ingest_video' | 'clean_transcript' | 'plan_outline' | 'write_section'
  | 'assemble_post' | 'fact_check' | 'revise_draft' | 'prepare_metadata'
  | 'human_review' | 'publish' | 'social_and_store';

type StepState = 'pending' | 'running' | 'done' | 'failed' | 'skipped' | 'waiting';

interface JobSummary {
  id: string; video_id: string; video_title: string; channel_name: string;
  thumbnail_url: string; status: JobStatus; pending_action: 'draft_review' | 'publish_approval' | null;
  faithfulness_score: number | null; revision_count: number;
  cost_usd: number; created_at: string; updated_at: string;
}

interface JobDetail extends JobSummary {
  video_url: string; duration_seconds: number; has_chapters: boolean;
  attribution_mode: 'own_video' | 'credited'; style_profile_id: string | null;
  model: string; max_revisions: number; min_faithfulness: number; budget_usd: number;
  current_step: PipelineStep | null;
  steps: { step: PipelineStep; state: StepState; started_at?: string; finished_at?: string;
           attempt: number; sub_items?: { id: string; label: string; state: StepState }[] }[];
  rejection_reason: string | null;          // e.g. "No transcript available", "Already published: <url>"
  errors: { step: PipelineStep; code: string; message: string; at: string; retryable: boolean }[];
  usage: { prompt_tokens: number; completion_tokens: number; cost_usd: number; by_step: Record<string, number> };
  checkpoint_id: string;                    // needed for resume calls
  current_draft_rev: number | null;
  devto_url: string | null; publish_status: 'published' | 'saved_as_draft' | 'not_published' | null;
}

interface VideoPreview {
  video_id: string; title: string; channel_name: string; thumbnail_url: string;
  duration_seconds: number; chapters: { title: string; start: number; end: number }[];
  transcript_available: boolean; transcript_language: string | null;
  eligible: boolean;
  ineligible_reason: null | 'no_transcript' | 'too_long_without_chapters' | 'already_published' | 'fetch_blocked';
  existing_article_url: string | null; estimated_cost_usd: { low: number; high: number };
}

interface DraftVersion { rev: number; kind: 'auto' | 'revised' | 'human_edit' | 'final';
  sha256: string; created_at: string; char_count: number; note?: string }

interface OutlineSection { id: string; heading: string; start: number; end: number; key_points: string[] }

interface Claim { text: string; supported: boolean; evidence: string; timestamp_seconds: number | null }

interface ReviewPayload {
  draft_rev: number; title: string; title_options: string[]; description: string; tags: string[];
  faithfulness_score: number; quality_scores: { readability: number; structure: number };
  unsupported_claims: string[]; outline: OutlineSection[]; angle: string; target_reader: string;
}

interface PublishRequest {
  title: string; tags: string[]; description: string; body_char_count: number;
  canonical_url: string | null; proposed_published: boolean; final_rev: number;
}

interface JobResult { devto_url: string; devto_article_id: number;
  publish_status: 'published' | 'saved_as_draft'; social: { linkedin: string; x: string } }

interface StyleProfile { id: string; name: string; examples: string[]; is_default: boolean; updated_at: string }

interface Integrations {
  openrouter: { connected: boolean; last4: string | null; verified_at: string | null; status: 'ok' | 'invalid' | 'unknown' };
  devto: { connected: boolean; username: string | null; verified_at: string | null; status: 'ok' | 'invalid' | 'unknown' };
}

interface UserSettings { default_model: string; default_attribution: 'own_video' | 'credited';
  default_max_revisions: number; default_min_faithfulness: number; default_budget_usd: number;
  default_style_profile_id: string | null }

interface Usage { period: string; jobs: number; cost_usd: number; tokens: number;
  daily: { date: string; cost_usd: number; jobs: number }[]; quota: { jobs_per_day: number; used_today: number } }
```

### Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/videos/preview` | `{url}` → `VideoPreview` |
| POST | `/jobs` | `{video_url, attribution_mode, style_profile_id?, model?, max_revisions, min_faithfulness, budget_usd}` → `202 {job_id}` |
| GET | `/jobs` | `?status=&q=&cursor=&limit=` → `{items: JobSummary[], next_cursor}` |
| GET | `/jobs/{id}` | `JobDetail` |
| GET | `/jobs/{id}/events` | SSE. Events: `step_started`, `step_finished`, `step_failed`, `sub_item_update`, `interrupt` (`{kind}`), `usage`, `status_changed`, `heartbeat` |
| POST | `/jobs/{id}/cancel` · `/retry` | `202` |
| DELETE | `/jobs/{id}` | `204` |
| GET | `/jobs/{id}/drafts` | `DraftVersion[]` |
| GET | `/jobs/{id}/drafts/{rev}` | `{rev, markdown}` |
| GET | `/jobs/{id}/outline` | `{angle, target_reader, sections: OutlineSection[]}` |
| GET | `/jobs/{id}/fact-check` | `{faithfulness_score, quality_scores, claims: Claim[], revision_notes: string[]}` |
| GET | `/jobs/{id}/review` | `ReviewPayload` (only while `pending_action = draft_review`) |
| POST | `/jobs/{id}/review` | `{action: 'approve'|'edit'|'revise'|'abort', title?, tags?, description?, markdown?, feedback?, expected_checkpoint_id}` → `202` |
| GET | `/jobs/{id}/publish-request` | `PublishRequest` |
| POST | `/jobs/{id}/publish` | `{decision: 'approve'|'edit'|'reject', published?: boolean, message?, expected_checkpoint_id}` → `202` |
| GET | `/jobs/{id}/result` | `JobResult` |
| POST | `/jobs/{id}/social/regenerate` | `JobResult['social']` |
| GET | `/articles` | `{items: {job_id, video_id, title, devto_url, publish_status, published_at}[], next_cursor}` |
| GET/POST/PUT/DELETE | `/style-profiles[/{id}]` | `StyleProfile` |
| GET/PUT | `/me/settings` | `UserSettings` |
| GET | `/me/integrations` | `Integrations` |
| PUT | `/me/integrations/openrouter` · `/devto` | `{api_key}` → verifies, then `Integrations` |
| POST | `/me/integrations/{provider}/test` | `{status}` |
| DELETE | `/me/integrations/{provider}` | `204` |
| GET | `/me/usage` | `?period=30d` → `Usage` |
| GET | `/models` | `{id, name, context_length, price_per_mtok_in, price_per_mtok_out}[]` |

**Resume rules (important):** every POST to `/review`, `/publish`, `/cancel` and `/retry` sends `expected_checkpoint_id` from the latest `JobDetail`, plus an `Idempotency-Key` header: a UUID created when the user clicks, reused if the request is retried. Disable the action buttons and show a spinner from the click until the SSE `status_changed` event arrives. Never fire the same action twice.

## 5. Pages (design every state: loading skeleton, empty, error, success)

### 5.1 `/login`
Centered card: logo, "Sign in with Google", an email-link option, and a short privacy note ("Your API keys are encrypted and never shown again").

### 5.2 `/dashboard`
- Header stats row: posts this month, average faithfulness, spend this month (vs. budget), and jobs awaiting you.
- **"Needs your attention"** section, shown only when non-empty: cards for jobs with `pending_action` or a retryable `failed` status. Each card has a thumbnail, title, the needed action ("Review draft", "Approve publish", "Retry failed step") and how long it's been waiting.
- **Jobs table**: thumbnail, title + channel, status badge, faithfulness (coloured pill: ≥0.85 green, 0.7–0.85 amber, <0.7 red), revisions, cost, updated (relative). Filter tabs by status group (All / In progress / Needs you / Completed / Failed), a search box, cursor pagination ("Load more"). Clicking a row opens the job. Running rows show a subtle animated progress indicator, updated live.
- Empty state: "Paste a YouTube link to write your first post" with an inline URL field that goes straight to `/jobs/new?url=…`.

### 5.3 `/jobs/new`
Two-step flow on one page:
1. **Paste URL**: a large input that accepts any YouTube URL format (watch, youtu.be, shorts, with timestamps) and auto-previews on paste (debounced). Show a skeleton while it loads.
2. **Preview card**: thumbnail, title, channel, duration, transcript language and a collapsible chapter list with timestamps. Show an **eligibility banner**:
   - eligible: green, with an estimated cost range ("≈ $0.04–$0.11 with deepseek-v4.1-flash")
   - `already_published`: link to the existing article and a disabled submit
   - `too_long_without_chapters`: explain the limit and suggest adding chapters
   - `no_transcript`: explain that the video has no captions
   - `fetch_blocked`: "YouTube temporarily blocked the request, try again in a minute", with a retry button
3. **Options form**, pre-filled from user settings:
   - attribution (segmented control: "It's my video" / "Credit the creator", with a one-line explanation of the credit block that gets added)
   - style profile (select, plus a "Create one" link)
   - model (searchable combobox from `/models` showing price per million tokens)
   - an "Advanced" accordion holding max auto-revisions (0–3 stepper), minimum faithfulness (slider 0.5–1.0, step 0.05, with a live label) and the job budget in USD
4. Submit ("Start writing"), then redirect to `/jobs/{id}`. Disable submit while keys are missing, the video is ineligible or the daily quota is used up (show the quota as "3 / 10 today").

### 5.4 `/jobs/[id]`: live pipeline
- Header: thumbnail, title, a link to the video, status badge, and overflow actions (Cancel, Delete, Retry, Copy job ID).
- **Pipeline stepper** (vertical on mobile, a horizontal graph or vertical timeline on desktop) mirroring the backend graph exactly:
  `Ingest → Clean transcript → Plan outline → Write sections (N parallel sub-items, each with its own state) → Assemble → Fact-check ⇄ Revise (a loop badge "revision 1 of 2") → Metadata → Human review ⏸ → Publish ⏸ → Social posts`.
  Each node shows its state icon, elapsed time, attempt number (when >1) and per-step cost on hover. Skipped steps are greyed out; a rejection at ingest shows the reason inline and ends the timeline.
- **Paused banner**, sticky at the top when `pending_action` is set: "Your draft is ready for review" → `/jobs/[id]/review`, or "Approve the dev.to publish" → `/jobs/[id]/publish`.
- **Side panel**:
  - the run config (model, thresholds, budget)
  - a live **usage meter** (tokens, cost vs. budget, warning at 80%)
  - draft versions (a list that opens a read-only preview)
  - a fact-check summary, once it's available
- **Errors panel**: each error shows its step, message, time and whether it's retryable. Provide "Retry from last checkpoint" (explain that completed steps won't re-run or re-bill) and "Copy error details".
- **Live activity log** (collapsible): a monospace feed of the SSE events with timestamps.
- Show a connection indicator for SSE (live / reconnecting / offline, falling back to polling every 5s).

### 5.5 `/jobs/[id]/review`: draft review (the most important screen; design it carefully)
Desktop uses three resizable columns; tablet and mobile use tabs (Draft / Video & outline / Quality).

- **Left, "Source"**: an embedded YouTube player (`youtube-nocookie`) with the outline below it: section headings with `mm:ss` timestamp chips and key points. Clicking a chip seeks the player. Show the angle and target reader at the top.
- **Center, "Draft"**:
  - a version dropdown (rev, kind, time), with tabs **Edit** / **Preview** / **Diff** (diff against any earlier version)
  - the editor: CodeMirror with markdown highlighting, line wrapping, word and character counts, and a reading-time estimate
  - the preview: rendered like a dev.to article (the `{% embed %}` liquid tag shows a YouTube card placeholder, code blocks are highlighted, and the "▶ Watch this part" links render as timestamp chips that seek the player on the left)
  - highlighting of sentences matching unsupported claims, in both the editor and preview, with a tooltip showing the evidence
  - an unsaved-changes indicator, with a guard against leaving the page
- **Right, "Quality & metadata"**:
  - a faithfulness gauge (score vs. the user's threshold line), and readability and structure scores out of 10
  - a **claims list**: supported ✓ / unsupported ⚠, with evidence text and a timestamp chip. Filter to show unsupported only. Clicking a claim scrolls the editor to it.
  - **Title**: radio cards for the AI title options plus a "Custom" input with a character counter (max 80 recommended, 128 hard)
  - **Description**: a textarea with a counter (max 150)
  - **Tags**: a chip input, max 4, auto-lowercased, stripped to letters and digits, with inline validation
- **Sticky action bar** (bottom):
  - **Approve**: primary. Disabled while there are unsaved edits; it changes to "Save edits & approve" instead.
  - **Request revision**: opens a sheet with a feedback textarea, quick-insert chips ("Shorter intro", "Add code examples", "More beginner friendly", "Fix unsupported claims") and a note that this triggers a new fact-check.
  - **Abort**: destructive, with a confirmation dialog that names what will happen.
  - Keyboard shortcuts: `Ctrl/Cmd+S` saves the edit locally, `Ctrl/Cmd+Enter` approves, `?` opens a shortcuts dialog.
- Autosave the edited draft to localStorage per job and rev, and offer to restore it on return.
- After submitting, show a full-width "Sending to the pipeline…" state, then route back to `/jobs/[id]`.

### 5.6 `/jobs/[id]/publish`: publish approval
- A summary card showing the title, tags (chips), description, body length, canonical URL and attribution block preview, with a "View final draft" side sheet that renders the full post.
- A **visibility choice**, as two large radio cards: "Save as private draft on dev.to" (default, recommended) and "Publish publicly now". Choosing public expands an inline confirmation: the user types the word `publish` (or ticks a checkbox stating that the post goes live on their dev.to account).
- Shows the dev.to account it will publish to (`@username` from integrations).
- Actions: **Approve** and **Reject** (with an optional reason). While the call is in flight, show "Sending to dev.to…". Show the success or failure result inline. If the call fails, show the dev.to error message and a Retry button (with a note that retries are safe and won't create duplicates).

### 5.7 `/jobs/[id]/result`
- A success state with a big link to the dev.to article, a publish-status badge (Draft / Public) and an "Open on dev.to" button. For drafts, add a hint: "Publish it from your dev.to dashboard when ready".
- Social cards for LinkedIn and X: editable textareas, live character counts (X limit 280), Copy buttons with copied feedback, and a "Regenerate" button.
- A run summary: total time, cost, tokens, revisions and final faithfulness.

### 5.8 `/articles`
A table or card grid of published articles: title, source video thumbnail, status (Draft / Public), date, and links to dev.to, the video and the job. Add search and an empty state.

### 5.9 `/settings/style-profiles`
A list of profiles, each with a name, example count, last update and a "Default" badge. The create/edit dialog has a name field, 1–3 example posts (markdown textareas with a word count, plus "paste from dev.to URL" as a disabled future option) and a "Set as default" switch. Deleting needs confirmation.

### 5.10 `/settings` (tabs)
- **Integrations**: two cards, OpenRouter and dev.to. Each has:
  - its status ("Connected · key ending in …a1f2 · verified 2h ago", "Invalid key" or "Not connected")
  - a password-type input for setting or replacing the key (never prefilled), with Save (which verifies it) and **Test connection** buttons, and Disconnect (with confirmation)
  - a help link explaining where to create the key
  - a note: "Keys are encrypted with Google Cloud KMS and stored separately from your content. They are never shown again after saving."
  - for dev.to, the connected `@username`
- **Defaults**: default model, attribution, max revisions, min faithfulness, budget per job and default style profile.
- **Account**: profile info, sign out, and a "Delete account & all data" danger zone (confirmation by typing your email).

### 5.11 `/usage`
- Period selector (7d / 30d / 90d), KPI tiles (jobs, cost, tokens, average cost per post) and a daily bar chart of cost (Recharts).
- A per-model breakdown table, plus the daily job quota with a progress bar.

### 5.12 Global states
- A 404 page for unknown jobs, a 403 page for a job owned by someone else (show it as "not found"), and an error boundary with a retry button.
- An offline banner when the network is lost.
- A maintenance banner driven by a `/status` flag.

## 6. Reusable components (build them as a small design system)

`AppShell`, `Sidebar`, `OnboardingBanner`, `StatusBadge` (one consistent colour and icon per `JobStatus`), `ScorePill`, `FaithfulnessGauge`, `PipelineStepper` and `PipelineNode`, `UsageMeter`, `VideoCard`, `VideoPreviewCard`, `EligibilityBanner`, `TimestampChip` (formatted `mm:ss` / `h:mm:ss`), `MarkdownEditor`, `MarkdownPreview` (dev.to style), `DraftDiff`, `VersionSelect`, `ClaimList` and `ClaimItem`, `TitlePicker`, `TagInput`, `CharCounter`, `ConfirmDialog` (with an optional typed confirmation), `ActionBar`, `CopyButton`, `KeyInputCard`, `EmptyState`, `ErrorState`, `ConnectionIndicator`, `KeyboardShortcutsDialog`.

Hooks: `useJob`, `useJobs`, `useJobEvents` (SSE that updates the TanStack Query cache), `useResumeAction` (handles `expected_checkpoint_id`, `Idempotency-Key`, button locking and 409 refetch), `useIntegrations`, `useUnsavedChangesGuard`, `useYouTubePlayer` (seekTo).

## 7. Quality bar

- Accessibility: WCAG 2.2 AA contrast in both themes; full keyboard navigation; visible focus rings; ARIA live regions for pipeline progress and toasts; status is never conveyed by colour alone.
- Performance: route-level code splitting; load CodeMirror, the diff viewer and the YouTube player lazily; images through `next/image`.
- Security: no API keys in client state beyond the input field's lifetime; no `dangerouslySetInnerHTML`; sanitise rendered markdown (`rehype-sanitize`); YouTube embeds via `youtube-nocookie.com`; a strict CSP-friendly setup.
- Configuration: `NEXT_PUBLIC_API_BASE_URL` and the Firebase public config come from env; MSW mocks turn on with `NEXT_PUBLIC_API_MOCKS=true`.
- Folder structure: `app/(public)/…`, `app/(app)/dashboard|jobs|articles|settings|usage/…`, `components/ui` (shadcn), `components/<feature>/…`, `lib/api`, `lib/auth`, `lib/hooks`, `lib/format`, `mocks/`.

## 8. Deliverables

1. The full Next.js project with every page and state above, wired to the MSW mock API with realistic fixtures. Include one job in each status, a long draft with code blocks, a failed job with a retryable error, an ineligible preview of each kind, and a user with missing keys.
2. A short README: setup, env vars, mock mode, and how to regenerate the API client from `openapi.json`.
3. Screenshots or a gallery page (`/dev/components`) showing every component in its states, in light and dark mode.
