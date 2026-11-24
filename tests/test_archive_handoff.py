import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import archive_handoff as handoff
import portable_pack as portable


class ArchiveHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pack = self.root / "source"
        self.pack.mkdir()
        files = {"report": "timeline.json", "dashboard": "timeline.html", "observations": "observations.json",
                 "log_summary": "logs.json", "notes": "notes.md"}
        for name in files.values():
            (self.pack / name).write_text(f"synthetic {name}", encoding="utf-8")
        manifest = {"schema_version": 1, "pack_type": "incident-investigation", "files": files,
                    "sha256": {name: portable.checksum((self.pack / name).read_bytes()) for name in files.values()}}
        (self.pack / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.archive = self.root / "evidence.zip"
        portable.export_pack(self.pack, self.archive)
        self.expected = portable.checksum(self.archive.read_bytes())
        self.destination, self.receipt = self.root / "imported", self.root / "receipt.json"

    def receive(self):
        return handoff.receive(self.archive, self.destination, self.receipt, self.expected)

    def test_inventory_without_extraction_or_private_paths(self):
        before = set(self.root.iterdir())
        report = handoff.inventory(self.archive)
        self.assertFalse(report["extracted"])
        self.assertEqual(len(report["members"]), 6)
        self.assertEqual(before, set(self.root.iterdir()))
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_inventory_matches_expected_hash(self):
        report = handoff.inventory(self.archive, self.expected.upper())
        self.assertTrue(report["expected_sha256_matched"])

    def test_wrong_expected_hash_stops_before_decompression(self):
        with patch.object(portable, "inspect_archive") as inspect:
            with self.assertRaises(ValueError):
                handoff.inventory(self.archive, "0" * 64)
            inspect.assert_not_called()

    def test_invalid_expected_hash_rejected(self):
        with self.assertRaises(ValueError):
            handoff.inventory(self.archive, "not-a-digest")

    def test_received_pack_and_external_receipt(self):
        result = self.receive()
        self.assertEqual(result["status"], "imported")
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(len(receipt["files"]), 6)
        self.assertEqual(len(list(self.destination.iterdir())), 6)
        self.assertNotIn(str(self.root), json.dumps(receipt))
        self.assertEqual(handoff.verify_receipt(self.receipt, self.destination)["status"], "verified")

    def test_import_uses_same_verified_snapshot_despite_source_change(self):
        original = portable.import_pack
        def changed_source(snapshot, destination):
            self.archive.write_bytes(b"changed after hash check")
            return original(snapshot, destination)
        with patch.object(portable, "import_pack", side_effect=changed_source):
            self.receive()
        self.assertEqual(handoff.verify_receipt(self.receipt, self.destination)["status"], "verified")

    def test_receipt_must_be_outside_imported_pack(self):
        with self.assertRaises(ValueError):
            handoff.receive(self.archive, self.destination, self.destination / "receipt.json", self.expected)
        self.assertFalse(self.destination.exists())

    def test_existing_receipt_preserved_before_import(self):
        self.receipt.write_text("preserve", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.receive()
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.receipt.read_text(), "preserve")

    def test_import_failure_does_not_create_receipt(self):
        with patch.object(portable, "import_pack", side_effect=OSError("failure")):
            with self.assertRaises(OSError):
                self.receive()
        self.assertFalse(self.receipt.exists())

    def test_receipt_failure_reports_partial_completion(self):
        with patch.object(handoff, "write_new_json", side_effect=OSError("receipt unavailable")):
            result = self.receive()
        self.assertEqual(result["status"], "imported_receipt_failed")
        self.assertTrue(self.destination.exists())
        self.assertFalse(self.receipt.exists())

    def test_changed_import_detected_by_receipt(self):
        self.receive()
        (self.destination / "notes.md").write_text("changed", encoding="utf-8")
        result = handoff.verify_receipt(self.receipt, self.destination)
        self.assertEqual(result["status"], "warning")
        self.assertIn({"file": "notes.md", "status": "changed"}, result["files"])

    def test_missing_import_artifact_detected(self):
        self.receive()
        (self.destination / "notes.md").unlink()
        result = handoff.verify_receipt(self.receipt, self.destination)
        self.assertIn({"file": "notes.md", "status": "missing"}, result["files"])

    def test_receipt_coverage_cannot_be_reduced(self):
        self.receive()
        record = json.loads(self.receipt.read_text())
        del record["files"]["notes.md"]
        self.receipt.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(ValueError):
            handoff.verify_receipt(self.receipt, self.destination)

    def test_inspection_output_never_overwrites_existing_evidence(self):
        target = self.root / "existing.json"
        target.write_text("preserve", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            code = handoff.main(["inspect", str(self.archive), "--output", str(target)])
        self.assertEqual(code, 2)
        self.assertEqual(target.read_text(), "preserve")

    def test_cli_receipt_roundtrip(self):
        command = [sys.executable, str(Path(handoff.__file__))]
        received = subprocess.run([*command, "receive", str(self.archive), "--expected-sha256", self.expected,
                                  "--destination", str(self.destination), "--receipt", str(self.receipt)],
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(received.returncode, 0, received.stderr)
        checked = subprocess.run([*command, "verify-receipt", str(self.receipt), "--destination", str(self.destination)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_verification_read_only(self):
        self.receive()
        before = {path.name: path.read_bytes() for path in self.destination.iterdir()}
        handoff.verify_receipt(self.receipt, self.destination)
        after = {path.name: path.read_bytes() for path in self.destination.iterdir()}
        self.assertEqual(before, after)


    def test_cli_receipt_failure_reports_imported_partial_result(self):
        with patch.object(handoff, "write_new_json", side_effect=OSError("receipt blocked")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = handoff.main(["receive", str(self.archive), "--expected-sha256", self.expected,
                                     "--destination", str(self.destination), "--receipt", str(self.receipt)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "imported_receipt_failed")
        self.assertTrue(self.destination.exists())
