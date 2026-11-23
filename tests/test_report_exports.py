import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from render_dashboard import main, render
from report_csv import export_csv, safe_cell
from test_incident_compare import snapshot


class ExportTests(unittest.TestCase):
    def test_formula_like_cells_are_neutralized(self):
        for value in ("=1+1", "+SUM(A1:A2)", "-cmd", "@function", "\t=1", "  =1"):
            self.assertTrue(safe_cell(value).startswith("'"))
        self.assertEqual(safe_cell("ordinary"), "ordinary")

    def test_csv_roundtrip_quotes_and_newlines(self):
        report = snapshot({'api,"quoted"\nname': "healthy"})
        rows = list(csv.reader(io.StringIO(export_csv(report))))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], 'api,"quoted"\nname')

    def test_csv_redacts_endpoint(self):
        report = snapshot({"api": "healthy"})
        self.assertNotIn("http://localhost", export_csv(report, redact_targets=True))

    def test_html_redacts_and_escapes(self):
        report = snapshot({"<script>bad</script>": "warning"})
        page = render(report, redact_targets=True)
        self.assertNotIn("<script>", page)
        self.assertNotIn("http://localhost", page)
        self.assertIn("[endpoint hidden]", page)

    def test_warnings_first_table_and_group_summary(self):
        page = render(snapshot({"aaa": "healthy", "zzz": "warning"}))
        self.assertLess(page.index('scope="row">zzz'), page.index('scope="row">aaa'))
        self.assertIn("Application groups", page)
        self.assertIn("50.0%", page)

    def test_export_command_writes_three_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.json"
            source.write_text(json.dumps(snapshot({"api": "healthy"})), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main([str(source), "--output", str(root / "out.html"), "--csv-output", str(root / "out.csv"),
                             "--analytics-output", str(root / "stats.json"), "--redact-targets"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((root / "stats.json").read_text())["total"], 1)
            self.assertTrue((root / "out.html").exists())
            self.assertTrue((root / "out.csv").exists())

    def test_export_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "report.json"
            data = json.dumps(snapshot({"api": "healthy"}))
            source.write_text(data, encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(source), "--output", str(source)]), 2)
            self.assertEqual(source.read_text(encoding="utf-8"), data)

    def test_duplicate_output_destinations_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.json"
            source.write_text(json.dumps(snapshot({"api": "healthy"})), encoding="utf-8")
            output = root / "out"
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(source), "--output", str(output), "--csv-output", str(output)]), 2)
            self.assertFalse(output.exists())

    def test_warning_only_comparison_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["input", "--previous", "before", "--warnings-only", "--output", "out"]), 2)
