"""Tests for the dependency-free ``.env`` loader.

The loader matters because the app reads its DeepSeek key from the
environment. If the file is not parsed correctly the system falls back to
the extractive engine and the failure looks like a slow API rather than a
missing key.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.envfile import _strip_quotes, load_env  # noqa: E402


class EnvFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self._temp_dir.name) / ".env"
        self._saved: dict[str, str | None] = {}

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temp_dir.cleanup()

    def _write(self, content: str) -> None:
        self.env_path.write_text(content, encoding="utf-8")

    def _track(self, key: str) -> None:
        if key not in self._saved:
            self._saved[key] = os.environ.get(key)

    def test_parses_plain_assignment(self) -> None:
        self._write("DEEPSEEK_API_KEY=sk-test-123\n")
        loaded = load_env(self.env_path)
        self.assertEqual(loaded["DEEPSEEK_API_KEY"], "sk-test-123")

    def test_ignores_comments_and_blank_lines(self) -> None:
        self._write("# a comment\n\nDEEPSEEK_MODEL=deepseek-chat\n")
        loaded = load_env(self.env_path)
        self.assertNotIn("# a comment", loaded)
        self.assertEqual(loaded["DEEPSEEK_MODEL"], "deepseek-chat")

    def test_strips_quotes(self) -> None:
        self._write('DEEPSEEK_API_KEY="sk-quoted"\n')
        self.assertEqual(load_env(self.env_path)["DEEPSEEK_API_KEY"], "sk-quoted")

    def test_keeps_export_prefix(self) -> None:
        self._write("export DEEPSEEK_API_KEY=sk-exported\n")
        self.assertEqual(load_env(self.env_path)["DEEPSEEK_API_KEY"], "sk-exported")

    def test_value_may_contain_equals_sign(self) -> None:
        self._write("DEEPSEEK_BASE_URL=https://example.com/v1?a=b\n")
        self.assertEqual(
            load_env(self.env_path)["DEEPSEEK_BASE_URL"],
            "https://example.com/v1?a=b",
        )

    def test_existing_environment_value_wins(self) -> None:
        self._track("DEEPSEEK_MODEL")
        os.environ["DEEPSEEK_MODEL"] = "already-set"
        self._write("DEEPSEEK_MODEL=from-file\n")
        load_env(self.env_path)
        self.assertEqual(os.environ["DEEPSEEK_MODEL"], "already-set")

    def test_missing_file_is_not_an_error(self) -> None:
        loaded = load_env(Path(self._temp_dir.name) / "nope.env")
        self.assertEqual(loaded, {})

    def test_strip_quotes_leaves_unquoted_value(self) -> None:
        self.assertEqual(_strip_quotes("plain"), "plain")
        self.assertEqual(_strip_quotes("'single'"), "single")
        self.assertEqual(_strip_quotes('"double"'), "double")

    def test_ignores_line_without_assignment(self) -> None:
        self._write("JUST_A_WORD\nDEEPSEEK_MODEL=m\n")
        loaded = load_env(self.env_path)
        self.assertNotIn("JUST_A_WORD", loaded)


if __name__ == "__main__":
    unittest.main()
