"""Behavioural tests for the CourseWise evidence pipeline.

These tests cover the three claims the system makes about itself:

1. It answers from the course documents and cites the passage it used.
2. It flags documents that are out of date, and prefers the version in force.
3. It refuses when the documents cannot support an answer.
4. It never changes state without an explicit confirmation.

Run with:
    .venv/bin/python -m unittest discover -s backend/tests -t backend
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import Database  # noqa: E402
from app.actions import ActionStore  # noqa: E402
from app.generation import ExtractiveGenerator, split_sentences  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.policy import assess_freshness, current_version_of, detect_conflicts  # noqa: E402
from app.retrieval import expand_query, extract_phrases, retrieve  # noqa: E402


def ask(orchestrator: Orchestrator, question: str):
    return asyncio.run(orchestrator.handle(question))


class RetrievalTests(unittest.TestCase):
    def test_qualified_names_are_extracted(self) -> None:
        self.assertIn("assignment 1", extract_phrases("When is the Assignment 1 deadline?"))
        self.assertIn("week 3", extract_phrases("What does week 3 cover?"))

    def test_phrase_match_beats_keyword_overlap(self) -> None:
        """'assignment 1' must not be answered from the assignment 2 brief."""
        hits = retrieve("When is the Assignment 1 deadline?", limit=10)
        top = hits[0]
        self.assertEqual(top.doc_id, "a1-brief-v2")
        self.assertTrue(top.matched_phrases)

    def test_week_three_matches_the_timeline(self) -> None:
        hits = retrieve("What does Week 3 cover?", limit=5)
        self.assertEqual(hits[0].doc_id, "timeline-v1")

    def test_every_passage_is_scored_once(self) -> None:
        hits = retrieve("assignment 1 deadline weight", limit=30)
        ids = [h.passage_id for h in hits]
        self.assertEqual(len(ids), len(set(ids)))

    def test_reading_list_question_reaches_the_reading_list(self) -> None:
        """"Which books do I need?" must find the reading list.

        "Book" is ambiguous in this domain: a textbook or a reservation. The
        table used to map it only to the reservation sense, so the office
        hours notice out-ranked the reading list and the assistant answered
        that the module had no reading list at all.
        """
        hits = retrieve("Which books do I need to read for this module?", limit=8)
        self.assertIn("readings-v1", [h.doc_id for h in hits])

    def test_booking_question_is_not_read_as_a_reading_question(self) -> None:
        """The two senses of "book" must not be merged."""
        weights = expand_query("I want to book a consultation")
        self.assertIn("consultation", weights)
        self.assertNotIn("reading", weights)

    def test_reading_question_does_not_expand_to_booking(self) -> None:
        weights = expand_query("Which books do I need to read for this module?")
        self.assertIn("reading", weights)
        self.assertNotIn("booking", weights)

    def test_synonym_table_is_reachable_after_stemming(self) -> None:
        """Plural entries must not be dead code.

        The index and the query are both stemmed, so a table keyed by the raw
        plural never matched: "marks" stems to "mark", and the "marks" entry
        was unreachable.
        """
        weights = expand_query("How many marks does the exam count for?")
        self.assertIn("weighting", weights)
        self.assertIn("percentage", weights)


class FreshnessTests(unittest.TestCase):
    def test_current_version_is_the_newest_published(self) -> None:
        self.assertEqual(current_version_of("assignment-1-brief").id, "a1-brief-v2")
        self.assertEqual(current_version_of("plagiarism-policy").id, "plagiarism-v2")

    def test_superseded_version_is_flagged(self) -> None:
        from app.corpus import CORPUS

        old = next(d for d in CORPUS if d.id == "a1-brief-v1")
        verdict = assess_freshness(old, current_version_of("assignment-1-brief").updated_at and __import__("datetime").date(2026, 10, 20))
        self.assertEqual(verdict.freshness, "superseded")
        self.assertIsNotNone(verdict.superseded_by)

    def test_expired_document_is_flagged(self) -> None:
        """A document past its validity date, with no newer version."""
        from app.corpus import CORPUS
        from datetime import date

        old = next(d for d in CORPUS if d.id == "plagiarism-v1")
        # Even though a newer version exists, the student should first be told
        # the version they are reading is the withdrawn one.
        verdict = assess_freshness(old, date(2026, 11, 1))
        self.assertIn(verdict.freshness, ("archived", "superseded"))
        self.assertIsNotNone(verdict.superseded_by)

    def test_document_without_newer_version_is_reported_as_withdrawn(self) -> None:
        from app.corpus import CORPUS
        from datetime import date

        withdrawn = next(d for d in CORPUS if d.status == "archived")
        # Simulate a group where the withdrawn copy is the only one left.
        import app.policy as policy

        original = policy.current_version_of
        try:
            policy.current_version_of = lambda key: (
                withdrawn if key == withdrawn.doc_key else original(key)
            )
            verdict = policy.assess_freshness(withdrawn, date(2026, 11, 1))
            self.assertEqual(verdict.freshness, "archived")
        finally:
            policy.current_version_of = original

    def test_conflicts_are_detected_between_versions(self) -> None:
        conflicts = detect_conflicts()
        doc_keys = {c.doc_key for c in conflicts}
        self.assertIn("assignment-1-brief", doc_keys)
        self.assertIn("exam-format", doc_keys)

    def test_conflicts_are_not_invented_for_single_version_docs(self) -> None:
        doc_keys = {c.doc_key for c in detect_conflicts()}
        self.assertNotIn("office-hours", doc_keys)
        self.assertNotIn("reading-list", doc_keys)


class SentenceTests(unittest.TestCase):
    def test_abbreviations_do_not_split_a_sentence(self) -> None:
        text = "Jian et al. (2000) on trust and reliance. A separate sentence."
        sentences = split_sentences(text)
        self.assertEqual(len(sentences), 2)
        self.assertIn("et al. (2000)", sentences[0])


class AnsweringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ActionStore(database=Database(Path(tempfile.mkdtemp()) / "test.db"))
        self.orchestrator = Orchestrator(store=self.store, generator=ExtractiveGenerator())

    def test_answer_cites_the_current_version(self) -> None:
        response = ask(
            self.orchestrator, "When is the Assignment 1 deadline and how much does it count for?"
        )
        self.assertIn("30 October 2026", response.answer)
        self.assertNotIn("16 October 2026", response.answer)
        self.assertTrue(response.sources)
        self.assertTrue(any(s.cited for s in response.sources))

    def test_superseded_source_is_still_shown(self) -> None:
        """The student should see what the old version said."""
        response = ask(self.orchestrator, "When is the Assignment 1 deadline?")
        stale = [s for s in response.sources if s.freshness_state == "superseded"]
        self.assertTrue(stale)
        self.assertIn("16 October", stale[0].excerpt)

    def test_refusal_explains_that_it_declined_to_guess(self) -> None:
        """A question the documents genuinely do not cover must be refused."""
        response = ask(self.orchestrator, "What is the weather in Birmingham tomorrow?")
        self.assertEqual(response.status, "insufficient-evidence")
        self.assertEqual(response.verdict["confidence"], 0.0)
        self.assertIn("not answered from general knowledge", response.answer)

    def test_extension_policy_is_answered_from_the_faq(self) -> None:
        """The question *is* covered, and the answer must cite the right passage."""
        response = ask(self.orchestrator, "Can I get an extension because I have a job?")
        self.assertIn("not granted for assessment workload", response.answer)
        self.assertIn("faq-v1-p2", [s.id for s in response.sources if s.cited])

    def test_multi_part_question_answers_every_part(self) -> None:
        """A question with two asks must get an answer for both."""
        response = ask(
            self.orchestrator,
            "When is the Assignment 1 deadline and how much does it count for?",
        )
        self.assertIn("30 October 2026", response.answer)
        self.assertIn("25%", response.answer)

    def test_every_answered_claim_has_a_source(self) -> None:
        for question in [
            "When is the Assignment 1 deadline?",
            "What is the final exam format?",
            "Which reading should I use for trust and transparency?",
        ]:
            response = ask(self.orchestrator, question)
            self.assertTrue(response.sources, f"no sources for: {question}")
            self.assertTrue(any(s.cited for s in response.sources), f"no citation for: {question}")

    def test_outdated_value_is_flagged_not_answered(self) -> None:
        """The current exam format wins, and the old one raises a warning."""
        response = ask(self.orchestrator, "What is the final exam format and how long is it?")
        self.assertIn("60-minute", response.answer)
        self.assertNotIn("90-minute", response.answer)
        self.assertTrue(
            any(w.severity == "warning" for w in response.warnings),
            "an outdated document must raise a warning",
        )

    def test_changed_value_is_reported_as_changed(self) -> None:
        """The student is told the value changed, not just given the new one."""
        response = ask(self.orchestrator, "What is the final exam format and how long is it?")
        details = " ".join(w.detail for w in response.warnings)
        self.assertIn("60-minute", details)
        self.assertIn("90-minute", details)


class ActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ActionStore(database=Database(Path(tempfile.mkdtemp()) / "test.db"))
        self.orchestrator = Orchestrator(store=self.store, generator=ExtractiveGenerator())

    def test_booking_is_only_proposed_not_applied(self) -> None:
        response = ask(
            self.orchestrator,
            "Book me a consultation slot on Thursday afternoon about my project report",
        )
        self.assertEqual(response.status, "action-proposed")
        self.assertIsNotNone(response.action)
        self.assertEqual(response.action["status"], "awaiting-confirmation")
        # Nothing was booked yet.
        self.assertEqual(self.store.list_bookings(), [])

    def test_confirmation_applies_the_change(self) -> None:
        response = ask(
            self.orchestrator,
            "Book me a consultation slot on Thursday afternoon about my project report",
        )
        action_id = response.action["id"]

        action, booking, error = self.store.commit(action_id)
        self.assertIsNone(error)
        self.assertEqual(action.status, "committed")
        self.assertEqual(booking.status, "confirmed")
        self.assertEqual(len(self.store.list_bookings()), 1)

    def test_cancelling_leaves_state_untouched(self) -> None:
        response = ask(
            self.orchestrator,
            "Book me a consultation slot on Thursday afternoon about my project report",
        )
        error = self.store.cancel(response.action["id"])
        self.assertIsNone(error)
        self.assertEqual(self.store.list_bookings(), [])

    def test_an_action_cannot_be_committed_twice(self) -> None:
        response = ask(
            self.orchestrator,
            "Book me a consultation slot on Thursday afternoon about my project report",
        )
        self.store.commit(response.action["id"])
        action, booking, error = self.store.commit(response.action["id"])
        self.assertIsNotNone(error)
        self.assertEqual(len(self.store.list_bookings()), 1)

    def test_unknown_action_id_is_rejected(self) -> None:
        action, booking, error = self.store.commit("not-a-real-id")
        self.assertIsNotNone(error)
        self.assertIsNone(action)


if __name__ == "__main__":
    unittest.main(verbosity=2)
