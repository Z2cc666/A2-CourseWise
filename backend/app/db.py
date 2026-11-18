"""SQLite persistence for CourseWise.

The system keeps everything in one SQLite file rather than in Python
constants or a JSON blob:

* ``documents`` / ``passages`` — the versioned course corpus, seeded once
  from ``corpus.py`` and then owned by the database.
* ``conversations`` / ``messages`` — chat history, so a conversation can be
  resumed and the model can see what was said earlier.
* ``slots`` / ``bookings`` — consultation slots and the bookings made
  against them.
* ``pending_actions`` — actions that have been proposed but not yet
  confirmed.

SQLite is used rather than a server database because the whole system runs
locally from one file, which keeps the deliverable simple to run and to
inspect. The schema is created on first use and the corpus is seeded only
when the ``documents`` table is empty, so edits made in the database are
never overwritten.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "coursewise.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    doc_key      TEXT NOT NULL,
    title        TEXT NOT NULL,
    kind         TEXT NOT NULL,
    owner        TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    status       TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    authored_by  TEXT NOT NULL DEFAULT '',
    expires_at   TEXT,
    applies_to   TEXT NOT NULL DEFAULT '[]',
    source_url   TEXT
);

CREATE INDEX IF NOT EXISTS documents_doc_key ON documents(doc_key);

CREATE TABLE IF NOT EXISTS passages (
    id        TEXT PRIMARY KEY,
    doc_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    heading   TEXT NOT NULL,
    text      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS passages_doc_id ON passages(doc_id);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    citations       TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS slots (
    slot_date TEXT NOT NULL,
    slot_time TEXT NOT NULL,
    tutor     TEXT NOT NULL,
    PRIMARY KEY (slot_date, slot_time)
);

CREATE TABLE IF NOT EXISTS bookings (
    id         TEXT PRIMARY KEY,
    slot_date  TEXT NOT NULL,
    slot_time  TEXT NOT NULL,
    topic      TEXT NOT NULL,
    status     TEXT NOT NULL,
    booked_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_actions (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL,
    title       TEXT NOT NULL,
    preview     TEXT NOT NULL,
    fields      TEXT NOT NULL,
    consequence TEXT NOT NULL,
    reversible  INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);
"""


class DatabaseLocked(RuntimeError):
    """The database file is held by another program and cannot be written.

    Raised instead of the bare ``sqlite3.OperationalError`` so that the API
    can tell the user what to do. The usual cause is a database browser
    opened on the same file: it holds a write lock for as long as it stays
    open, and every write the assistant attempts then fails.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        super().__init__(
            f"The database at {self.path} is locked by another program. "
            "Close any database browser or editor that has this file open "
            "(DB Browser for SQLite, a spreadsheet tool, another copy of the "
            "server) and try again. Nothing was changed."
        )


class Database:
    """A thin wrapper around one SQLite file.

    A connection is created per operation. SQLite handles this efficiently
    for a local single-process application, and it avoids the shared-state
    problems a long-lived connection would bring with the test suite.
    """

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._counter = 0
        self._ensure_schema()
        self.ensure_seeded()

    # -- connection ----------------------------------------------------- #

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The busy timeout is deliberately short. A lock held by another
        # program will not clear on its own, so waiting ten seconds only
        # delays the explanation of what went wrong; failing promptly lets
        # the user close the other program and retry. Normal contention
        # between threads of this process is resolved by ``self._lock``
        # before SQLite is reached.
        connection = sqlite3.connect(self.path, timeout=3.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _is_locked(self, error: Exception) -> bool:
        """Whether an error is SQLite reporting a locked database.

        Another program can hold the file — a database browser opened on the
        same path, for instance — and SQLite then refuses to write until it
        is closed. The default message, "database is locked", says nothing
        about who holds it, so the same failure looks like a bug in the
        application.
        """
        message = str(error).lower()
        return "locked" in message or "busy" in message

    def _ensure_schema(self) -> None:
        connection = self.connect()
        try:
            # Write-ahead logging lets a reader work while a writer holds the
            # file, which matters when the database is also open in a
            # browser. It is a persistent property of the file, so it is
            # set once here. If the file is held by another program the
            # pragma fails, and the journal mode simply stays as it was —
            # the application still works, just without the extra
            # concurrency.
            try:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.commit()
            except sqlite3.OperationalError:
                pass
            connection.executescript(SCHEMA)
            connection.commit()
        finally:
            connection.close()

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        connection = self.connect()
        try:
            return connection.execute(sql, tuple(params)).fetchall()
        finally:
            connection.close()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run a write and return the new rowid, or the row count.

        A locked database is reported as :class:`DatabaseLocked` so that the
        caller can explain what happened. The raw SQLite message — "database
        is locked" — is the same whether the file is held by another program
        or by a transaction of our own, and the first case is the one a
        student or a reviewer runs into.
        """
        with self._lock:
            connection = self.connect()
            try:
                cursor = connection.execute(sql, tuple(params))
                connection.commit()
                return cursor.lastrowid or cursor.rowcount
            except sqlite3.OperationalError as exc:
                if self._is_locked(exc):
                    raise DatabaseLocked(self.path) from exc
                raise
            finally:
                connection.close()

    # -- seeding -------------------------------------------------------- #

    def is_seeded(self) -> bool:
        row = self.query_one("SELECT COUNT(*) AS n FROM documents")
        return bool(row and row["n"])

    def seed_documents(self, documents: Iterable[Any]) -> None:
        """Insert the corpus. Only called when ``documents`` is empty."""
        with self._lock:
            connection = self.connect()
            try:
                for doc in documents:
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO documents
                            (id, doc_key, title, kind, owner, updated_at, status,
                             summary, authored_by, expires_at, applies_to, source_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            doc.id,
                            doc.doc_key,
                            doc.title,
                            doc.kind,
                            doc.owner,
                            doc.updated_at,
                            doc.status,
                            doc.summary,
                            doc.authored_by,
                            doc.expires_at,
                            json.dumps(list(doc.applies_to)),
                            doc.source_url,
                        ),
                    )
                    for position, passage in enumerate(doc.passages):
                        connection.execute(
                            """
                            INSERT OR REPLACE INTO passages
                                (id, doc_id, position, heading, text)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (passage.id, doc.id, position, passage.heading, passage.text),
                        )
                connection.commit()
            finally:
                connection.close()

    def seed_slots(self, slots: Iterable[dict[str, str]]) -> None:
        with self._lock:
            connection = self.connect()
            try:
                for slot in slots:
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO slots (slot_date, slot_time, tutor)
                        VALUES (?, ?, ?)
                        """,
                        (slot["date"], slot["time"], slot["tutor"]),
                    )
                connection.commit()
            finally:
                connection.close()

    def ensure_seeded(self) -> None:
        """Insert the seed corpus and slots the first time the database is used.

        Called by the application on start-up and by anything that creates a
        database of its own — a test fixture, for instance — so a fresh
        database is never left empty.
        """
        if not self.is_seeded():
            from .corpus_seed import SEED_CORPUS

            self.seed_documents(SEED_CORPUS)

        if not self.query_one("SELECT 1 FROM slots LIMIT 1"):
            from .slots import AVAILABLE_SLOTS

            self.seed_slots(AVAILABLE_SLOTS)

    # -- conversations --------------------------------------------------- #

    def create_conversation(self, title: str) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        # The id carries a random suffix so that two processes writing to the
        # same file cannot collide, and a counter so that ids created inside
        # the same second still differ. ``hash`` is not usable here: Python
        # randomises string hashing per process, so the same title would
        # produce a different id on every run.
        self._counter += 1
        conversation_id = f"c-{now}-{self._counter:04d}-{uuid4().hex[:6]}"
        self.execute(
            """
            INSERT INTO conversations (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, title, now, now),
        )
        return conversation_id

    def list_conversations(self, limit: int = 50) -> list[dict]:
        rows = self.query(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM messages m
                     WHERE m.conversation_id = c.id) AS message_count
            FROM conversations c
            ORDER BY c.updated_at DESC, c.rowid DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict | None:
        row = self.query_one(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        return dict(row) if row else None

    def delete_conversation(self, conversation_id: str) -> bool:
        existing = self.get_conversation(conversation_id)
        if existing is None:
            return False
        self.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        self.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return True

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        if self.get_conversation(conversation_id) is None:
            return False
        self.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, datetime.now().isoformat(timespec="seconds"), conversation_id),
        )
        return True

    def touch_conversation(self, conversation_id: str) -> None:
        self.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), conversation_id),
        )

    # -- messages -------------------------------------------------------- #

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        citations: list[str] | None = None,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        row_id = self.execute(
            """
            INSERT INTO messages (conversation_id, role, content, citations, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, role, content, json.dumps(citations or []), now),
        )
        self.touch_conversation(conversation_id)
        return row_id if isinstance(row_id, int) else 0

    def list_messages(
        self,
        conversation_id: str,
        limit: int = 200,
    ) -> list[dict]:
        rows = self.query(
            """
            SELECT role, content, citations, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["citations"] = json.loads(item["citations"])
            except (TypeError, ValueError):
                item["citations"] = []
            out.append(item)
        return out

    def recent_turns(
        self,
        conversation_id: str,
        limit: int = 6,
    ) -> list[dict[str, str]]:
        """The last few user/assistant turns, for conversational context."""
        rows = self.query(
            """
            SELECT role, content FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    # -- slots and bookings ---------------------------------------------- #

    def list_slots(self) -> list[dict[str, str]]:
        rows = self.query(
            "SELECT slot_date, slot_time, tutor FROM slots ORDER BY slot_date, slot_time"
        )
        return [
            {"date": row["slot_date"], "time": row["slot_time"], "tutor": row["tutor"]}
            for row in rows
        ]

    def list_bookings(self) -> list[dict]:
        rows = self.query(
            """
            SELECT id, slot_date, slot_time, topic, status, booked_at
            FROM bookings ORDER BY slot_date, slot_time
            """
        )
        return [dict(row) for row in rows]

    def insert_booking(
        self,
        booking_id: str,
        slot_date: str,
        slot_time: str,
        topic: str,
        status: str = "confirmed",
    ) -> None:
        self.execute(
            """
            INSERT INTO bookings (id, slot_date, slot_time, topic, status, booked_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                booking_id,
                slot_date,
                slot_time,
                topic,
                status,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

    def update_booking_status(self, booking_id: str, status: str) -> None:
        self.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))

    def delete_booking(self, booking_id: str) -> None:
        self.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))

    # -- pending actions -------------------------------------------------- #

    def insert_action(self, action: dict) -> None:
        self.execute(
            """
            INSERT INTO pending_actions
                (id, kind, status, title, preview, fields, consequence,
                 reversible, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action["id"],
                action["kind"],
                action["status"],
                action["title"],
                action["preview"],
                json.dumps(action["fields"]),
                action["consequence"],
                1 if action["reversible"] else 0,
                action["createdAt"],
            ),
        )

    def get_action(self, action_id: str) -> dict | None:
        row = self.query_one(
            """
            SELECT id, kind, status, title, preview, fields, consequence,
                   reversible, created_at
            FROM pending_actions WHERE id = ?
            """,
            (action_id,),
        )
        if row is None:
            return None
        item = dict(row)
        try:
            item["fields"] = json.loads(item["fields"])
        except (TypeError, ValueError):
            item["fields"] = []
        item["reversible"] = bool(item["reversible"])
        return item

    def update_action_status(self, action_id: str, status: str) -> None:
        self.execute(
            "UPDATE pending_actions SET status = ? WHERE id = ?", (status, action_id)
        )


#: The process-wide database. Modules import this rather than constructing
#: their own, so that one connection sees one consistent set of rows.
db = Database()
