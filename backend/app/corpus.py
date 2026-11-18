"""The course document corpus, loaded from the database.

The seed data lives in ``corpus_seed.py`` as plain Python objects. On first
run that data is inserted into SQLite; after that the database is the source
of truth, so documents can be edited or replaced without touching the code.

The rest of the system works with :class:`CourseDoc` and :class:`Passage`
objects, which are rebuilt from database rows here. That keeps the retrieval
and policy modules independent of where the corpus lives.
"""

from __future__ import annotations

import json

from .db import Database, db
from .models import MODULE, CourseDoc, DocKind, DocStatus, Passage

__all__ = [
    "CORPUS",
    "CourseDoc",
    "DocKind",
    "DocStatus",
    "MODULE",
    "Passage",
    "ensure_seeded",
    "load_corpus",
]


def _row_to_doc(row, passages: list[Passage]) -> CourseDoc:
    try:
        applies_to = tuple(json.loads(row["applies_to"]))
    except (TypeError, ValueError):
        applies_to = ()

    return CourseDoc(
        id=row["id"],
        doc_key=row["doc_key"],
        title=row["title"],
        kind=row["kind"],
        owner=row["owner"],
        updated_at=row["updated_at"],
        status=row["status"],
        summary=row["summary"] or "",
        authored_by=row["authored_by"] or "",
        passages=tuple(passages),
        expires_at=row["expires_at"],
        applies_to=applies_to,
        source_url=row["source_url"],
    )


def load_corpus(database: Database | None = None) -> tuple[CourseDoc, ...]:
    """Read every document and its passages out of the database."""
    database = database or db

    documents: list[CourseDoc] = []
    for row in database.query("SELECT * FROM documents ORDER BY doc_key, updated_at"):
        passage_rows = database.query(
            "SELECT id, heading, text FROM passages WHERE doc_id = ? ORDER BY position",
            (row["id"],),
        )
        passages = [
            Passage(id=p["id"], heading=p["heading"], text=p["text"])
            for p in passage_rows
        ]
        documents.append(_row_to_doc(row, passages))

    return tuple(documents)


def ensure_seeded(database: Database | None = None) -> None:
    """Insert the seed corpus the first time the database is used."""
    (database or db).ensure_seeded()


ensure_seeded()

#: The corpus, as read from the database at import time. Retrieval and policy
#: modules index this, so it is a snapshot rather than a live query.
CORPUS: tuple[CourseDoc, ...] = load_corpus()
