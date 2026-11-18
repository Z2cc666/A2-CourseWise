"""Tests for the DeepSeek answer backend.

The real endpoint needs a key, so these tests stand up a local mock of the
OpenAI-compatible API and point ``DEEPSEEK_BASE_URL`` at it. They check the
parts that are ours — the request we build, the way we read the response —
rather than the parts that belong to the provider.
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generation import DeepSeekGenerator, GenerationInput  # noqa: E402
from app.policy import EvidenceItem, FreshnessVerdict  # noqa: E402


class _MockDeepSeek(BaseHTTPRequestHandler):
    """Records the request and replies with a canned completion."""

    received: dict = {}
    #: Set by the test to change what the server replies with.
    reply: dict = {}
    status: int = 200

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) or b"{}"

        type(self).received = {
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "body": json.loads(raw),
        }

        if type(self).status != 200:
            payload = json.dumps({"error": {"message": "boom"}}).encode("utf-8")
            self.send_response(type(self).status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        body = type(self).received["body"]
        payload = json.dumps(
            {
                "id": "chatcmpl-test",
                "model": body.get("model", "deepseek-chat"),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "The final exam is a 60-minute paper [1].",
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


def make_evidence(freshness: str = "current") -> EvidenceItem:
    return EvidenceItem(
        doc_id="exam-format-v2",
        doc_key="exam-format",
        title="Final Exam Format",
        kind="schedule",
        owner="Module Teaching Team",
        updated_at="2026-10-01",
        updated_at_label="1 October 2026",
        summary="",
        source_url=None,
        passage_id="exam-v2-p1",
        heading="Exam structure",
        text="The final exam is a 60-minute written paper consisting of four questions.",
        score=7.2,
        matched_terms=("exam",),
        matched_phrases=(),
        freshness=FreshnessVerdict(
            freshness=freshness,
            label="Current" if freshness == "current" else "Superseded",
            detail="Published 1 October 2026.",
        ),
    )


class DeepSeekBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        _MockDeepSeek.received = {}
        _MockDeepSeek.status = 200

        self.server = HTTPServer(("127.0.0.1", 0), _MockDeepSeek)
        self.port = self.server.server_address[1]
        # A short poll interval keeps ``shutdown`` from dominating the
        # runtime of the test suite.
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.thread.start()

        self.generator = DeepSeekGenerator(
            model="deepseek-chat",
            base_url=f"http://127.0.0.1:{self.port}",
            api_key="sk-test-key",
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _generate(self, **overrides):
        gen_input = GenerationInput(
            question=overrides.get("question", "What is the final exam format?"),
            evidence=overrides.get("evidence", [make_evidence()]),
            must_refuse=overrides.get("must_refuse", False),
            warnings=overrides.get("warnings", ()),
            history=overrides.get("history", ()),
        )
        return self.generator.generate(gen_input)

    # -- request shape -------------------------------------------------- #

    def test_request_is_well_formed(self) -> None:
        self._generate()
        received = _MockDeepSeek.received

        self.assertEqual(received["path"], "/chat/completions")
        self.assertEqual(received["auth"], "Bearer sk-test-key")
        self.assertTrue(received["content_type"].startswith("application/json"))
        self.assertEqual(received["body"]["model"], "deepseek-chat")
        self.assertFalse(received["body"]["stream"])
        self.assertEqual(received["body"]["temperature"], 0)

    def test_system_prompt_is_sent(self) -> None:
        self._generate()
        messages = _MockDeepSeek.received["body"]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("ONLY from the numbered course-document passages", messages[0]["content"])

    def test_passages_are_numbered_and_labelled(self) -> None:
        self._generate()
        prompt = _MockDeepSeek.received["body"]["messages"][-1]["content"]
        self.assertIn("[1]", prompt)
        self.assertIn("Status: CURRENT", prompt)
        self.assertIn("60-minute", prompt)

    def test_stale_passage_is_flagged_in_the_prompt(self) -> None:
        self._generate(evidence=[make_evidence(freshness="superseded")])
        prompt = _MockDeepSeek.received["body"]["messages"][-1]["content"]
        self.assertIn("SUPERSEDED", prompt)

    def test_history_is_passed_through(self) -> None:
        self._generate(
            history=(
                {"role": "user", "content": "When is the Assignment 1 deadline?"},
                {"role": "assistant", "content": "30 October 2026."},
            )
        )
        messages = _MockDeepSeek.received["body"]["messages"]
        # system + two history turns + the current question
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[2]["role"], "assistant")

    def test_refusal_instruction_is_included(self) -> None:
        self._generate(must_refuse=True)
        prompt = _MockDeepSeek.received["body"]["messages"][-1]["content"]
        self.assertIn("the retrieved evidence is insufficient", prompt)

    # -- response handling ---------------------------------------------- #

    def test_answer_and_citations_are_extracted(self) -> None:
        answer = self._generate()
        self.assertIn("60-minute", answer.text)
        self.assertEqual(answer.cited_passage_ids, ("exam-v2-p1",))
        self.assertEqual(answer.backend, "deepseek")
        self.assertEqual(answer.model, "deepseek-chat")

    def test_out_of_range_citation_is_ignored(self) -> None:
        """A citation to a passage that does not exist must not be trusted."""
        _MockDeepSeek.reply = {}
        answer = self._generate()
        self.assertNotIn("exam-v2-p99", answer.cited_passage_ids)

    def test_api_error_does_not_raise(self) -> None:
        _MockDeepSeek.status = 401
        answer = self._generate()
        self.assertEqual(answer.cited_passage_ids, ())
        self.assertIn("error", answer.text.lower())

    def test_unreachable_api_does_not_raise(self) -> None:
        generator = DeepSeekGenerator(
            model="deepseek-chat",
            base_url="http://127.0.0.1:1",  # nothing listens here
            api_key="sk-test-key",
            timeout=1.0,
        )
        answer = generator.generate(
            GenerationInput(
                question="Anything?",
                evidence=[make_evidence()],
                must_refuse=False,
            )
        )
        self.assertEqual(answer.cited_passage_ids, ())
        self.assertIn("could not reach", answer.text.lower())

if __name__ == "__main__":
    unittest.main(verbosity=2)
