import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audit_bundles as auditor
from artifact_integrity import digest
from fault_lab import application_lab
from run_diagnostics import run as run_bundle


class BundleAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runs = self.root / "runs"
        self.runs.mkdir()

    def bundle(self, name="run-one", checksums=True):
        path = self.runs / name
        path.mkdir()
        for filename, text in (("services.json", '{"status":"healthy"}'), ("dashboard.html", "<html>safe fixture</html>")):
            (path / filename).write_text(text, encoding="utf-8")
        manifest = {"schema_version": 1, "files": {"report": "services.json", "dashboard": "dashboard.html"}}
        if checksums:
            manifest["sha256"] = {filename: digest(path / filename) for filename in manifest["files"].values()}
        (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.runs / "latest.json").write_text(json.dumps({"bundle": name}), encoding="utf-8")
        return path

    def test_all_intact_bundles_verify(self):
        self.bundle()
        self.bundle("run-two")
        result = auditor.audit(self.runs)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["summary"]["verified"], 2)

    def test_changed_artifact_detected(self):
        path = self.bundle()
        (path / "dashboard.html").write_text("changed", encoding="utf-8")
        result = auditor.audit(self.runs)
        self.assertIn("changed:dashboard.html", result["bundles"][0]["issues"])
        self.assertIn("latest_bundle_not_verified", result["pointer_issues"])

    def test_missing_artifact_detected(self):
        path = self.bundle()
        (path / "services.json").unlink()
        self.assertIn("missing:services.json", auditor.audit_bundle(path)["issues"])

    def test_legacy_bundle_is_not_falsely_verified(self):
        path = self.bundle(checksums=False)
        self.assertIn("legacy_bundle_without_checksums", auditor.audit_bundle(path)["issues"])

    def test_partial_bundle_is_warning(self):
        (self.runs / "run-partial").mkdir()
        self.assertEqual(auditor.audit(self.runs)["summary"]["warning"], 1)

    def test_unlisted_file_flagged(self):
        path = self.bundle()
        (path / "leftover.tmp").write_text("incomplete", encoding="utf-8")
        self.assertIn("unlisted:leftover.tmp", auditor.audit_bundle(path)["issues"])

    def test_manifest_requires_checksum_coverage(self):
        path = self.bundle()
        manifest_path = path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        del manifest["sha256"]["dashboard.html"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertEqual(auditor.audit_bundle(path)["status"], "warning")

    def test_unsafe_filename_rejected_before_hashing(self):
        path = self.bundle()
        manifest = {"schema_version": 1, "files": {"report": "../outside.json", "dashboard": "dashboard.html"}}
        (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with patch.object(auditor, "digest") as hash_file:
            self.assertEqual(auditor.audit_bundle(path)["status"], "warning")
            hash_file.assert_not_called()

    def test_stale_latest_pointer(self):
        self.bundle()
        (self.runs / "latest.json").write_text('{"bundle":"../outside"}', encoding="utf-8")
        self.assertIn("latest_pointer_missing_or_unknown_bundle", auditor.audit(self.runs)["pointer_issues"])

    def test_missing_latest_pointer(self):
        self.bundle()
        (self.runs / "latest.json").unlink()
        self.assertEqual(auditor.audit(self.runs)["status"], "warning")

    def test_limit_rejects_incomplete_scan(self):
        self.bundle()
        self.bundle("run-two")
        with self.assertRaises(ValueError):
            auditor.audit(self.runs, 1)

    def test_empty_directory_is_not_verified(self):
        self.assertEqual(auditor.audit(self.runs)["status"], "warning")

    def test_output_cannot_overwrite_audited_evidence(self):
        self.bundle()
        target = self.runs / "latest.json"
        original = target.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            code = auditor.main([str(self.runs), "--output", str(target)])
        self.assertEqual(code, 2)
        self.assertEqual(target.read_bytes(), original)

    def test_audit_is_read_only_and_cli_writes_external_evidence(self):
        self.bundle()
        before = {path.relative_to(self.runs).as_posix(): path.read_bytes()
                  for path in self.runs.rglob("*") if path.is_file()}
        output = self.root / "audit.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(auditor.main([str(self.runs), "--output", str(output)]), 0)
        after = {path.relative_to(self.runs).as_posix(): path.read_bytes()
                 for path in self.runs.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(json.loads(output.read_text())["status"], "verified")

    def test_real_diagnostic_bundle_cli_audit(self):
        catalogue = self.root / "services.json"
        with application_lab() as lab:
            catalogue.write_text(json.dumps({"version": 1, "services": [{
                "name": "api", "type": "http", "target": lab.url + "/ready"
            }]}), encoding="utf-8")
            run_bundle(catalogue, self.runs)
        process = subprocess.run([sys.executable, str(Path(auditor.__file__)), str(self.runs)],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["summary"]["verified"], 1)
