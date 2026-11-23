import tempfile
import unittest
from pathlib import Path

from run_profile import profile_arguments


class ProfileTests(unittest.TestCase):
    def parse(self, content):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "profile.json"
            target.write_text(content, encoding="utf-8")
            return profile_arguments(target)

    def test_repeatable_targets(self):
        self.assertEqual(self.parse('{"samples":3,"http":["http://localhost/","http://127.0.0.1/"]}'),
                         ["--samples=3", "--http=http://localhost/", "--http=http://127.0.0.1/"])

    def test_reject_ambiguous_profiles(self):
        for content in ('[]', '{"typo":1}', '{"samples":true}', '{"http":"x"}',
                        '{"samples":1,"samples":2}', '{"samples":null}'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.parse(content)

    def test_value_cannot_inject_flags(self):
        self.assertEqual(self.parse('{"output":"--show-history"}'), ["--output=--show-history"])



