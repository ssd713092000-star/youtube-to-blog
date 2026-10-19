"""Structured-output schemas for LLM calls."""

from pydantic import BaseModel, Field


class Glossary(BaseModel):
    terms: list[str] = Field(description="Technical terms, product names and acronyms spelled correctly")


class OutlineSectionModel(BaseModel):
    heading: str
    chapter_idxs: list[int] = Field(description="Indices of the chapters that belong in this section, in order")
    key_points: list[str]


class Outline(BaseModel):
    angle: str = Field(description="One sentence: the blog post's angle")
    target_reader: str
    tags: list[str] = Field(description="Up to 4 lowercase dev.to tags, letters and digits only")
    sections: list[OutlineSectionModel]


class Framing(BaseModel):
    intro: str = Field(description="Hook plus 1-2 paragraphs, markdown, no heading")
    tldr: list[str] = Field(description="3-5 short TL;DR bullets")
    conclusion: str = Field(description="Short conclusion in markdown, no heading")


class ClaimCheck(BaseModel):
    text: str
    supported: bool
    evidence: str = ""
    section: str = Field(default="", description="Heading of the section the claim appears in, or 'intro'/'conclusion'")
    timestamp: str = Field(default="", description="hh:mm:ss or mm:ss of the supporting transcript passage, if any")


class FactCheck(BaseModel):
    claims: list[ClaimCheck]
    readability: float = Field(description="1-10")
    structure: float = Field(description="1-10")
    revision_notes: list[str]


class RevisionItem(BaseModel):
    target: str = Field(description="Exactly one of the listed targets: a section heading, 'intro', 'tldr' or 'conclusion'")
    instruction: str = Field(description="Concrete change to make in that part")


class RevisionPlan(BaseModel):
    items: list[RevisionItem]


class Metadata(BaseModel):
    title_options: list[str] = Field(description="3 title options, each under 80 characters")
    description: str = Field(description="One-sentence summary, under 150 characters")
    tags: list[str] = Field(description="Max 4 lowercase tags, letters and digits only")


class Social(BaseModel):
    linkedin: str
    x: str = Field(description="Under 270 characters")
