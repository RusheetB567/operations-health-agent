import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_integrity import digest, verify
import run_diagnostics
from test_incident_compare import snapshot


class ArtifactIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.artifact = self.root / "services.json"
        self.artifact.write_text("original", encoding="utf-8")
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({"sha256": {"services.json": digest(self.artifact)}}), encoding="utf-8")

    def test_unchanged_bundle_verifies(self):
        self.assertEqual(verify(self.root)["status"], "verified")

    def test_modified_artifact_detected(self):
        self.artifact.write_text("modified", encoding="utf-8")
        self.assertEqual(verify(self.root)["artifacts"][0]["status"], "changed")

    def test_missing_artifact_detected(self):
        self.artifact.unlink()
        self.assertEqual(verify(self.root)["artifacts"][0]["status"], "missing")

    def test_path_escape_rejected(self):
        self.manifest.write_text(json.dumps({"sha256": {"../outside.json": "0" * 64}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_generated_bundle_contains_verifiable_digests(self):
        catalogue = self.root / "catalogue.json"
        catalogue.write_text(json.dumps({"version": 1, "services": [{"name": "api", "type": "http", "target": "http://localhost/"}]}), encoding="utf-8")
        report = snapshot({"api": "healthy"})
        report.update(status="healthy", summary={"total": 1, "healthy": 1, "warning": 0})
        with patch.object(run_diagnostics, "monitor", return_value=report):
            result = run_diagnostics.run(catalogue, self.root / "runs")
        self.assertEqual(verify(result["bundle"])["status"], "verified")
