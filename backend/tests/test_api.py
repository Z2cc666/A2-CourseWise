"""HTTP contract tests.

The frontend is plain JavaScript that renders whatever JSON the API returns,
so the API's shape *is* the frontend's contract. These tests pin that shape
down, so a change to a field name cannot silently break the UI.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The tests must not depend on the developer's shell or on a ``.env`` file
# sitting next to the repository. The key is set to an empty string rather
# than removed: the app loads ``.env`` on import and would otherwise put the
# key back, switching the backend to DeepSeek and making the contract test
# below fail for reasons that have nothing to do with the code. An empty
# value is falsy, so the app stays on the extractive engine.
for _variable in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ[_variable] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Database  # noqa: E402
from app.main import app  # noqa: E402,F401


class ApiContractTests(unittest.TestCase):
    """Contract tests against the real ASGI app.

    The action store is replaced with an isolated one for each test, so the
    tests do not depend on — or corrupt — whatever a previous run left in
    ``backend/data/state.json``.
    """

    def setUp(self) -> None:
        import tempfile

        from app import main

        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_store = main.store
        self._original_orchestrator = main.orchestrator

        main.store = main.ActionStore(database=Database(Path(self._temp_dir.name) / "test.db"))
        main.orchestrator = main.Orchestrator(store=main.store)

        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        from app import main

        main.store = self._original_store
        main.orchestrator = self._original_orchestrator
        self._temp_dir.cleanup()

    def test_health_reports_backend_and_module(self) -> None:
        payload = self.client.get("/api/health").json()
        self.assertTrue(payload["ok"])
        self.assertIn(payload["backend"], ("extractive", "llm", "deepseek"))
        self.assertIn("documents", payload)
        self.assertEqual(payload["module"]["code"], "CS-26352")

    def test_ask_returns_the_full_response_shape(self) -> None:
        payload = self.client.post(
            "/api/ask", json={"question": "When is the Assignment 1 deadline?"}
        ).json()

        for key in (
            "status",
            "answer",
            "verdict",
            "sources",
            "warnings",
            "notFound",
            "relatedQuestions",
            "backend",
            "consideredDocuments",
        ):
            self.assertIn(key, payload)

        self.assertIn(payload["status"], (
            "answered",
            "answered-with-caveats",
            "insufficient-evidence",
            "action-proposed",
            "action-unavailable",
        ))

        # "action-proposed" is a promise: a confirmation card is waiting for
        # the student. A response that carries the status without an action
        # claims a pending confirmation that does not exist, which is
        # exactly what the two-phase protocol is meant to prevent.
        if payload["status"] == "action-proposed":
            self.assertIsNotNone(payload["action"])
            self.assertEqual(payload["action"]["status"], "awaiting-confirmation")
        else:
            self.assertIsNone(payload["action"])

        verdict = payload["verdict"]
        self.assertIn("label", verdict)
        self.assertIn("detail", verdict)
        self.assertIsInstance(verdict["confidence"], float)

        for source in payload["sources"]:
            for key in (
                "id",
                "title",
                "kind",
                "owner",
                "updatedAtLabel",
                "section",
                "excerpt",
                "relevance",
                "freshness",
                "cited",
            ):
                self.assertIn(key, source)
            self.assertIn(
                source["freshness"]["freshness"],
                ("current", "expiring", "expired", "superseded", "archived"),
            )

        for warning in payload["warnings"]:
            self.assertIn(warning["severity"], ("info", "caution", "warning"))
            self.assertIn("title", warning)
            self.assertIn("detail", warning)

    def test_empty_question_is_rejected(self) -> None:
        response = self.client.post("/api/ask", json={"question": "   "})
        self.assertEqual(response.status_code, 400)

    def test_refusal_carries_no_sources(self) -> None:
        payload = self.client.post(
            "/api/ask", json={"question": "What is the weather in Birmingham tomorrow?"}
        ).json()
        self.assertEqual(payload["status"], "insufficient-evidence")
        self.assertEqual(payload["sources"], [])
        self.assertIsNotNone(payload["notFound"])

    def test_action_is_proposed_and_confirmable(self) -> None:
        payload = self.client.post(
            "/api/ask",
            json={"question": "Book me a consultation slot on Thursday afternoon about my report"},
        ).json()

        self.assertEqual(payload["status"], "action-proposed")
        action = payload["action"]
        self.assertEqual(action["status"], "awaiting-confirmation")
        self.assertIn("fields", action)
        self.assertIn("consequence", action)

        # Nothing is booked until the student confirms.
        self.assertEqual(self.client.get("/api/bookings").json()["bookings"], [])

        confirmed = self.client.post(f"/api/actions/{action['id']}/confirm")
        self.assertEqual(confirmed.status_code, 200)
        body = confirmed.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["booking"]["status"], "confirmed")

        # A second confirmation must not create a second booking.
        repeat = self.client.post(f"/api/actions/{action['id']}/confirm")
        self.assertEqual(repeat.status_code, 409)

    def test_cancelling_an_action_changes_nothing(self) -> None:
        payload = self.client.post(
            "/api/ask",
            json={"question": "Book me a consultation slot on Wednesday morning about my report"},
        ).json()
        self.assertIsNotNone(payload["action"])
        action_id = payload["action"]["id"]

        before = len(self.client.get("/api/bookings").json()["bookings"])
        cancelled = self.client.post(f"/api/actions/{action_id}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertTrue(cancelled.json()["ok"])

        after = len(self.client.get("/api/bookings").json()["bookings"])
        self.assertEqual(before, after)

    def test_unknown_action_id_is_rejected(self) -> None:
        response = self.client.post("/api/actions/does-not-exist/confirm")
        self.assertEqual(response.status_code, 409)

    def test_locked_database_is_reported_as_a_conflict(self) -> None:
        """A locked database must not surface as a server fault.

        Another program holding the file — a database browser, most often —
        is a condition the user can resolve by closing it. A 500 hides
        that behind a stack trace; a 409 with an explanation tells them
        what to do.
        """
        from app import main
        from app.db import DatabaseLocked

        original = main.store.database.execute

        def locked(sql, params=()):
            raise DatabaseLocked(main.store.database.path)

        main.store.database.execute = locked
        try:
            response = self.client.post(
                "/api/ask", json={"question": "Book me a consultation slot on Thursday"}
            )
        finally:
            main.store.database.execute = original

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["error"], "database-locked")
        self.assertIn("locked", body["detail"].lower())

    def test_unavailable_slot_is_not_reported_as_a_pending_action(self) -> None:
        """A request that matches no slot must not claim a confirmation card.

        The two-phase protocol works by showing the student what would change
        before anything changes. If the system reports "awaiting your
        confirmation" while carrying no action, the student is told a
        confirmation is pending that does not exist.
        """
        payload = self.client.post(
            "/api/ask",
            json={"question": "Book a consultation slot on Sunday about my report"},
        ).json()

        self.assertEqual(payload["status"], "action-unavailable")
        self.assertIsNone(payload["action"])
        self.assertEqual(self.client.get("/api/bookings").json()["bookings"], [])

    def test_documents_endpoint_exposes_the_corpus(self) -> None:
        payload = self.client.get("/api/documents").json()
        self.assertGreater(len(payload["documents"]), 0)
        for doc in payload["documents"]:
            self.assertIn("title", doc)
            self.assertIn("freshness", doc)
            self.assertIn("status", doc)

    def test_slots_endpoint_lists_free_slots(self) -> None:
        payload = self.client.get("/api/slots").json()
        self.assertGreater(len(payload["slots"]), 0)
        for slot in payload["slots"]:
            self.assertIn("date", slot)
            self.assertIn("time", slot)
            self.assertIn("free", slot)

    def test_frontend_is_served(self) -> None:
        for path in ("/", "/static/styles.css", "/static/app.js"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    def test_spa_fallback_serves_the_app(self) -> None:
        response = self.client.get("/some/deep/route")
        self.assertEqual(response.status_code, 200)
        self.assertIn("CourseWise", response.text)

    def test_api_routes_are_not_shadowed_by_the_spa_fallback(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")
        self.assertIn("ok", response.json())


if __name__ == "__main__":
    unittest.main(verbosity=2)
