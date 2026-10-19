"""Draft representation. A draft is stored as JSON "parts" (intro, tldr, sections, conclusion) so revisions
can target one section at a time, plus the composed markdown that humans read and dev.to receives."""

import json
import re
from typing import Literal, TypedDict

from app.graph.state import BlogState, DraftVersion
from app.graph.util import fmt_time, now_iso
from app.services.blobs import BlobRef, BlobStore, job_path


class SectionPart(TypedDict):
    id: str
    heading: str
    markdown: str  # without the "Watch this part" link, which is appended on compose
    start: float
    link: str


class DraftParts(TypedDict):
    intro: str
    tldr: list[str]
    sections: list[SectionPart]
    conclusion: str


def watch_link(start: float, link: str) -> str:
    return f"[▶ Watch this part of the video ({fmt_time(start)})]({link})"


def compose(parts: DraftParts) -> str:
    tldr = "\n".join(f"- {b}" for b in parts["tldr"])
    body = "\n\n".join(f"{s['markdown'].strip()}\n\n{watch_link(s['start'], s['link'])}" for s in parts["sections"])
    return (
        f"{parts['intro'].strip()}\n\n**TL;DR**\n\n{tldr}\n\n{body}\n\n"
        f"## Conclusion\n\n{parts['conclusion'].strip()}"
    )


def section_is_valid(original: str, revised: str) -> bool:
    """A revised section must keep a level-2 heading and must not silently drop code blocks."""
    if not re.search(r"^## \S", revised, flags=re.M):
        return False
    if revised.count("```") % 2:
        return False
    return revised.count("```") >= original.count("```") or original.count("```") == 0


async def save_draft(blobs: BlobStore, state: BlogState, parts: DraftParts | None, markdown: str,
                     kind: Literal["auto", "revised", "human_edit", "final"], note: str | None = None
                     ) -> dict:
    """Write a new draft version and return the state update."""
    uid, jid = state["user_id"], state["job_id"]
    versions = list(state.get("draft_versions", []))
    rev = len(versions) + 1
    update: dict = {}
    if parts is not None:
        pj = json.dumps(parts, ensure_ascii=False)
        update["draft_parts_ref"] = await blobs.put_text(
            job_path(uid, jid, "drafts", f"r{rev}-parts", pj, "json"), pj, "application/json"
        )
    ref = await blobs.put_text(job_path(uid, jid, "drafts", f"r{rev}-{kind}", markdown), markdown)
    versions.append(DraftVersion(rev=rev, kind=kind, ref=ref, created_at=now_iso(), note=note))
    update.update({"draft_versions": versions, "draft_rev": rev})
    if kind in ("auto", "revised"):
        update["draft_ref"] = ref
    return update


def find_version(state: BlogState, rev: int) -> BlobRef | None:
    for v in state.get("draft_versions", []):
        if v["rev"] == rev:
            return v["ref"]
    return None
