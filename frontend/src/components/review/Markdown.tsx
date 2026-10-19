"use client";

import { diffLines } from "diff";
import { Children, isValidElement, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { TimestampChip } from "@/components/common";
import { cn } from "@/lib/utils";

const EMBED_RE = /^\{%\s*embed\s+(\S+)\s*%\}\s*$/gm;
const WATCH_RE = /youtu\.be\/[\w-]{11}\?t=(\d+)/;

// Allow highlight.js classes through the sanitizer.
const schema = {
  ...defaultSchema,
  attributes: { ...defaultSchema.attributes, code: [...(defaultSchema.attributes?.code ?? []), ["className", /^language-|^hljs/]], span: [["className", /^hljs/]] },
};

function textOf(node: React.ReactNode): string {
  return Children.toArray(node)
    .map((c) => (typeof c === "string" ? c : isValidElement<{ children?: React.ReactNode }>(c) ? textOf(c.props.children) : ""))
    .join("");
}

export interface ClaimHighlight {
  text: string;
  evidence: string;
}

function claimKey(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
}

/** dev.to-like rendering: {% embed %} becomes a video card, "▶ Watch" links become seek chips,
 *  and paragraphs containing unsupported claims are highlighted with the fact-checker's evidence. */
export function MarkdownPreview({ markdown, claims = [], onSeek }: { markdown: string; claims?: ClaimHighlight[]; onSeek?: (s: number) => void }) {
  const source = useMemo(() => markdown.replace(EMBED_RE, (_m, url: string) => `> 🎬 EMBED ${url}`), [markdown]);
  const keys = useMemo(() => claims.map((c) => ({ ...c, words: claimKey(c.text).split(" ").filter((w) => w.length > 3) })), [claims]);

  const match = (text: string) => {
    const t = claimKey(text);
    return keys.find((k) => k.words.length > 0 && k.words.filter((w) => t.includes(w)).length / k.words.length >= 0.7);
  };

  const components: Components = {
    blockquote({ children }) {
      const t = textOf(children);
      if (t.startsWith("🎬 EMBED ")) {
        const url = t.slice("🎬 EMBED ".length).trim();
        return (
          <div className="my-4 flex items-center gap-3 rounded-lg border border-border bg-sidebar p-3 text-sm not-italic">
            <span className="grid h-10 w-16 place-items-center rounded bg-black text-white">▶</span>
            <span className="min-w-0">
              <span className="block font-medium">YouTube embed</span>
              <span className="block truncate font-mono text-xs text-fg-subtle">{url}</span>
            </span>
          </div>
        );
      }
      return <blockquote>{children}</blockquote>;
    },
    a({ href, children }) {
      const m = href?.match(WATCH_RE);
      if (m && onSeek) {
        return (
          <span className="inline-flex items-center gap-1.5">
            <TimestampChip seconds={Number(m[1])} onSeek={onSeek} />
            <span className="text-xs text-fg-subtle">{textOf(children).replace(/^▶\s*/, "")}</span>
          </span>
        );
      }
      return (
        <a href={href} target="_blank" rel="noreferrer noopener">
          {children}
        </a>
      );
    },
    p({ children }) {
      const hit = keys.length ? match(textOf(children)) : undefined;
      if (!hit) return <p>{children}</p>;
      return (
        <p data-claim={hit.text} title={`Unsupported: ${hit.evidence || "not found in the transcript"}`} className="rounded bg-warning-bg/70 outline outline-1 outline-warning/40">
          {children}
        </p>
      );
    },
    li({ children }) {
      const hit = keys.length ? match(textOf(children)) : undefined;
      return <li className={hit ? "bg-warning-bg/70" : undefined} title={hit ? `Unsupported: ${hit.evidence}` : undefined}>{children}</li>;
    },
  };

  return (
    <div className="prose-devto">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeSanitize, schema], rehypeHighlight]} components={components}>
        {source}
      </ReactMarkdown>
    </div>
  );
}

export function DraftDiff({ before, after }: { before: string; after: string }) {
  const parts = useMemo(() => diffLines(before, after), [before, after]);
  return (
    <pre className="overflow-x-auto rounded-lg border border-border bg-surface p-3 font-mono text-[12.5px] leading-6 whitespace-pre-wrap">
      {parts.map((p, i) => (
        <span
          key={i}
          className={cn(p.added && "block bg-success-bg text-success", p.removed && "block bg-danger-bg text-danger line-through decoration-danger/40")}
        >
          {p.value
            .split("\n")
            .filter((l, idx, arr) => idx < arr.length - 1 || l)
            .map((l) => `${p.added ? "+ " : p.removed ? "- " : "  "}${l}`)
            .join("\n")}
          {"\n"}
        </span>
      ))}
    </pre>
  );
}
