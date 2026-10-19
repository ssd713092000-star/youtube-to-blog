"use client";

import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { languages } from "@codemirror/language-data";
import { EditorView } from "@codemirror/view";
import CodeMirror from "@uiw/react-codemirror";
import { useTheme } from "next-themes";
import { useMemo } from "react";

/** Loaded with next/dynamic (ssr: false) so CodeMirror stays out of the initial bundle. */
export default function MarkdownEditor({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { resolvedTheme } = useTheme();
  const extensions = useMemo(
    () => [
      markdown({ base: markdownLanguage, codeLanguages: languages }),
      EditorView.lineWrapping,
      EditorView.theme({
        "&": { fontSize: "13px", backgroundColor: "transparent" },
        ".cm-content": { fontFamily: "var(--font-mono)", padding: "12px 0" },
        ".cm-gutters": { backgroundColor: "transparent", border: "none", color: "var(--fg-faint)" },
        ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "color-mix(in srgb, var(--accent) 6%, transparent)" },
      }),
    ],
    [],
  );
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      extensions={extensions}
      theme={resolvedTheme === "dark" ? "dark" : "light"}
      basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: true }}
      aria-label="Draft markdown"
      minHeight="60vh"
    />
  );
}
