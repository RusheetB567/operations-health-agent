import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_profile


class ProfileValidationTests(unittest.TestCase):
    def check(self, content):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json"
            profile.write_text(content, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return run_profile.main([str(profile), "--check"])

    def test_validation_never_runs_monitor(self):
        with patch.object(run_profile.system_health, "main", side_effect=AssertionError):
            self.assertEqual(self.check('{"samples":3,"consecutive":2}'), 0)

    def test_invalid_types_and_ranges(self):
        for content in ('{"samples":1.5}', '{"samples":"3"}', '{"cpu-threshold":NaN}',
                        '{"memory-threshold":101}', '{"network-timeout":0}', '{"disk":123}',
                        '{"consecutive":2}', '{"http-status":600}', '{"max-reports":false}'):
            with self.subTest(content=content):
                self.assertEqual(self.check(content), 2)

    def test_invalid_targets(self):
        for content in ('{"tcp":["host:0"]}', '{"http":["http://user:secret@localhost"]}', '{"http":[12]}'):
            with self.subTest(content=content):
                self.assertEqual(self.check(content), 2)

    def test_valid_targets(self):
        self.assertEqual(self.check('{"tcp":["[::1]:443"],"http":["https://localhost/ready"]}'), 0)
