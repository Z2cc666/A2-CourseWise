"""Shared data structures for the course corpus.

Kept separate from both the seed data and the database loader so that the
three modules can import the same types without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

DocStatus = Literal["current", "superseded", "draft", "archived"]
DocKind = Literal[
    "assessment", "policy", "schedule", "module-info", "resource", "faq"
]


@dataclass(frozen=True)
class Passage:
    """One addressable chunk inside a document."""

    id: str
    heading: str
    text: str


@dataclass(frozen=True)
class CourseDoc:
    """A single published version of a course document."""

    id: str
    doc_key: str
    title: str
    kind: DocKind
    owner: str
    updated_at: str  # ISO date the version was published
    status: DocStatus
    summary: str
    authored_by: str
    passages: tuple[Passage, ...] = field(default_factory=tuple)
    expires_at: str | None = None
    applies_to: tuple[str, ...] = field(default_factory=tuple)
    source_url: str | None = None


MODULE = {
    "code": "CS-26352",
    "name": "Human-Centred Design for Intelligent Systems",
    "institution": "University of Birmingham",
    "term": "Autumn 2026",
}
