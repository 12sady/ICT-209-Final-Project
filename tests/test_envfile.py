"""envfile.py: reading settings from .env."""
import os
import tempfile
import unittest
from unittest import mock

import envfile


class EnvFileTests(unittest.TestCase):
    def test_parse_formats(self):
        text = '﻿# comment\n\nAI_MODEL=gemini-3.6-flash\nexport AI_BASE_URL="https://x/v1"\nAI_API_KEY = \'k-1\'\nnot a line\n=nokey\n'
        self.assertEqual(envfile.parse(text), {"AI_MODEL": "gemini-3.6-flash", "AI_BASE_URL": "https://x/v1", "AI_API_KEY": "k-1"})

    def test_load_does_not_override_and_skips_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w") as f:
                f.write("ENVTEST_A=from-file\nENVTEST_B=from-file\nENVTEST_C=\n")
            with mock.patch.dict(os.environ, {"ENVTEST_B": "typed"}):
                self.assertEqual(envfile.load(path), ["ENVTEST_A"])
                self.assertEqual(os.environ["ENVTEST_A"], "from-file")
                self.assertEqual(os.environ["ENVTEST_B"], "typed")
                self.assertNotIn("ENVTEST_C", os.environ)
            os.environ.pop("ENVTEST_A", None)

    def test_missing_file_is_fine(self):
        self.assertEqual(envfile.load("/nonexistent/.env"), [])


if __name__ == "__main__":
    unittest.main()
