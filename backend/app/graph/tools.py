import ast
import json
import re

from langchain_core.tools import tool

from app.graph.util import fmt_time, split_words


@tool
def validate_code_syntax(language: str, code: str) -> str:
    """Check that a code block is syntactically valid. Supports python and json.
    Returns 'OK' or a description of the error. Other languages are not checked."""
    lang = language.strip().lower()
    try:
        if lang in ("python", "py"):
            ast.parse(code)
        elif lang == "json":
            json.loads(code)
        else:
            return f"Not checked: no validator for '{language}'."
    except (SyntaxError, ValueError) as e:
        return f"INVALID {language}: {e}"
    return "OK"


def make_search_transcript_tool(chapters: list[dict]):
    """Keyword-overlap search over the cleaned transcript (no embeddings needed)."""
    passages: list[tuple[str, float, str]] = []
    for ch in chapters:
        for piece in split_words(ch["text"], 60):
            if piece:
                passages.append((ch["title"], ch["start"], piece))

    @tool
    def search_transcript(query: str) -> str:
        """Search the video transcript for passages relevant to a claim. Returns the top 3 passages
        with their chapter and timestamp. Use it to verify each factual claim in the draft."""
        q = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 3}
        scored = []
        for title, start, piece in passages:
            overlap = len(q & set(re.findall(r"[a-z0-9]+", piece.lower())))
            if overlap:
                scored.append((overlap, title, start, piece))
        scored.sort(key=lambda x: -x[0])
        if not scored:
            return "No relevant passage found."
        return "\n\n".join(f"[{fmt_time(s)} | {t}] <transcript>{p}</transcript>" for _, t, s, p in scored[:3])

    return search_transcript
