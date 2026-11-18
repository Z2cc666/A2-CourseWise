"""Tests for the SQLite layer.

The database holds everything the system knows: the corpus, the chat
history, the slots, the bookings and the pending actions. These tests
check that a fresh database is seeded correctly, that the seed is applied
only once, and that the parts that used to live in a JSON file still
behave the way the rest of the system expects.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.actions import ActionStore  # noqa: E402
from app.db import Database  # noqa: E402


class SeedingTests(unittest.TestCase):
    """A new database must arrive seeded, and stay that way."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._dir.name) / "fresh.db")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_a_fresh_database_is_seeded(self) -> None:
        self.assertEqual(len(self.db.query("SELECT * FROM documents")), 12)
        self.assertEqual(len(self.db.query("SELECT * FROM passages")), 46)
        self.assertEqual(len(self.db.query("SELECT * FROM slots")), 15)

    def test_the_seed_is_not_reapplied(self) -> None:
        """Re-seeding must not duplicate the corpus."""
        before = len(self.db.query("SELECT * FROM documents"))
        self.db.ensure_seeded()
        self.assertEqual(len(self.db.query("SELECT * FROM documents")), before)

    def test_a_document_edited_in_the_database_survives_a_restart(self) -> None:
        """The database is the source of truth, not the seed file."""
        self.db.execute(
            "UPDATE documents SET title = ? WHERE id = ?",
            ("Edited by the reviewer", "exam-v2"),
        )

        reopened = Database(self.db.path)
        row = reopened.query_one(
            "SELECT title FROM documents WHERE id = ?", ("exam-v2",)
        )
        self.assertEqual(row["title"], "Edited by the reviewer")

    def test_passages_are_ordered_within_a_document(self) -> None:
        rows = self.db.query(
            "SELECT position FROM passages WHERE doc_id = ? ORDER BY position",
            ("exam-v2",),
        )
        positions = [row["position"] for row in rows]
        self.assertEqual(positions, sorted(positions))


class ConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._dir.name) / "chat.db")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_a_conversation_starts_empty(self) -> None:
        conversation_id = self.db.create_conversation("First chat")
        self.assertEqual(self.db.list_messages(conversation_id), [])

    def test_messages_are_stored_in_order(self) -> None:
        conversation_id = self.db.create_conversation("First chat")
        self.db.add_message(conversation_id, "user", "What is the exam format?")
        self.db.add_message(conversation_id, "assistant", "A 60-minute paper.")

        messages = self.db.list_messages(conversation_id)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["role"], "assistant")

    def test_recent_turns_returns_the_last_turns_newest_last(self) -> None:
        conversation_id = self.db.create_conversation("First chat")
        for index in range(5):
            self.db.add_message(conversation_id, "user", f"question {index}")
            self.db.add_message(conversation_id, "assistant", f"answer {index}")

        turns = self.db.recent_turns(conversation_id, limit=4)
        self.assertEqual(len(turns), 4)
        self.assertEqual(turns[-1]["content"], "answer 4")

    def test_deleting_a_conversation_removes_its_messages(self) -> None:
        conversation_id = self.db.create_conversation("First chat")
        self.db.add_message(conversation_id, "user", "hello")
        self.assertTrue(self.db.delete_conversation(conversation_id))
        self.assertIsNone(self.db.get_conversation(conversation_id))
        self.assertEqual(self.db.list_messages(conversation_id), [])

    def test_conversations_are_listed_newest_first(self) -> None:
        first = self.db.create_conversation("First")
        self.db.add_message(first, "user", "hello")
        second = self.db.create_conversation("Second")

        listed = self.db.list_conversations()
        self.assertEqual(len(listed), 2)
        self.assertEqual(listed[0]["id"], second)


class BookingStoreTests(unittest.TestCase):
    """The action store used to write a JSON file; it now uses the database."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._dir.name) / "actions.db")
        self.store = ActionStore(database=self.db)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_nothing_is_booked_until_the_action_is_committed(self) -> None:
        action = self.store.propose_booking(
            {"date": "2026-11-12", "time": "13:00", "tutor": "Dr A. Rahman"},
            "my report",
        )
        self.assertEqual(action.status, "awaiting-confirmation")
        self.assertEqual(self.store.list_bookings(), [])
        self.assertEqual(len(self.db.query("SELECT * FROM bookings")), 0)

    def test_committing_writes_one_booking(self) -> None:
        action = self.store.propose_booking(
            {"date": "2026-11-12", "time": "13:00", "tutor": "Dr A. Rahman"},
            "my report",
        )
        committed, booking, error = self.store.commit(action.id)

        self.assertIsNone(error)
        self.assertEqual(committed.status, "committed")
        self.assertEqual(booking.slot_date, "2026-11-12")
        self.assertEqual(len(self.store.list_bookings()), 1)

    def test_an_action_cannot_be_committed_twice(self) -> None:
        action = self.store.propose_booking(
            {"date": "2026-11-12", "time": "13:00", "tutor": "Dr A. Rahman"},
            "my report",
        )
        self.store.commit(action.id)
        _, _, error = self.store.commit(action.id)

        self.assertIsNotNone(error)
        self.assertEqual(len(self.store.list_bookings()), 1)

    def test_cancelling_writes_nothing(self) -> None:
        action = self.store.propose_booking(
            {"date": "2026-11-12", "time": "13:00", "tutor": "Dr A. Rahman"},
            "my report",
        )
        error = self.store.cancel(action.id)

        self.assertIsNone(error)
        self.assertEqual(self.store.list_bookings(), [])
        self.assertEqual(len(self.db.query("SELECT * FROM bookings")), 0)

    def test_a_booked_slot_is_no_longer_free(self) -> None:
        action = self.store.propose_booking(
            {"date": "2026-11-12", "time": "13:00", "tutor": "Dr A. Rahman"},
            "my report",
        )
        self.store.commit(action.id)

        self.assertFalse(self.store.slot_available("2026-11-12", "13:00"))
        self.assertTrue(self.store.slot_available("2026-11-12", "15:30"))

    def test_a_booking_survives_a_new_store_on_the_same_database(self) -> None:
        action = self.store.propose_booking(
            {"date": "2026-11-12", "time": "13:00", "tutor": "Dr A. Rahman"},
            "my report",
        )
        self.store.commit(action.id)

        reopened = ActionStore(database=Database(self.db.path))
        self.assertEqual(len(reopened.list_bookings()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
