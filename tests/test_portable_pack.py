import contextlib
import io
import json
import stat
import struct
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

import portable_pack as portable
from artifact_integrity import verify


class PortablePackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pack = self.root / "source"
        self.pack.mkdir()
        self.archive = self.root / "evidence.zip"
        self.destination = self.root / "imported"
        files = {"report": "timeline.json", "dashboard": "timeline.html", "observations": "observations.json",
                 "log_summary": "logs.json", "notes": "notes.md"}
        for name in files.values():
            (self.pack / name).write_text(f"synthetic {name}", encoding="utf-8")
        self.manifest = {"schema_version": 1, "pack_type": "incident-investigation", "files": files,
                         "sha256": {name: portable.checksum((self.pack / name).read_bytes()) for name in files.values()}}
        self.write_manifest()

    def write_manifest(self):
        (self.pack / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def export(self):
        return portable.export_pack(self.pack, self.archive)

    def rewrite_archive(self, changes=None, extras=None):
        with zipfile.ZipFile(self.archive) as source:
            entries = [(entry, source.read(entry)) for entry in source.infolist()]
        with zipfile.ZipFile(self.archive, "w") as target:
            for entry, data in entries:
                target.writestr(entry, (changes or {}).get(entry.filename, data))
            for name, data in (extras or {}).items():
                target.writestr(name, data)

    def malformed_archive(self, names):
        with zipfile.ZipFile(self.archive, "w") as target:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                for name in names:
                    target.writestr(name, b"fixture")

    def test_complete_export_verify_import_roundtrip(self):
        result = self.export()
        self.assertEqual(result["artifacts"], 5)
        report, _ = portable.inspect_archive(self.archive)
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["archive_entries"], 7)
        portable.import_pack(self.archive, self.destination)
        self.assertEqual(verify(self.destination)["status"], "verified")
        for source in self.pack.iterdir():
            self.assertEqual(source.read_bytes(), (self.destination / source.name).read_bytes())

    def test_repeated_exports_reproducible_in_same_runtime(self):
        self.export()
        second = self.root / "second.zip"
        portable.export_pack(self.pack, second)
        self.assertEqual(self.archive.read_bytes(), second.read_bytes())

    def test_changed_source_rejected(self):
        (self.pack / "notes.md").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.export()
        self.assertFalse(self.archive.exists())

    def test_missing_source_rejected(self):
        (self.pack / "notes.md").unlink()
        with self.assertRaises(OSError):
            self.export()

    def test_existing_archive_not_overwritten(self):
        self.archive.write_bytes(b"preserve")
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(self.archive.read_bytes(), b"preserve")

    def test_archive_cannot_be_created_inside_source_pack(self):
        with self.assertRaises(ValueError):
            portable.export_pack(self.pack, self.pack / "out.zip")

    def test_changed_archive_payload_reported_as_warning(self):
        self.export()
        self.rewrite_archive(changes={"notes.md": b"tampered but valid ZIP"})
        report, _ = portable.inspect_archive(self.archive)
        self.assertEqual(report["status"], "warning")
        self.assertTrue(any(issue["issue"] == "manifest_digest_mismatch" for issue in report["issues"]))

    def test_unverified_archive_creates_no_destination(self):
        self.export()
        self.rewrite_archive(changes={"notes.md": b"tampered"})
        with self.assertRaises(ValueError):
            portable.import_pack(self.archive, self.destination)
        self.assertFalse(self.destination.exists())

    def test_existing_import_destination_preserved(self):
        self.export()
        self.destination.mkdir()
        (self.destination / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaises(ValueError):
            portable.import_pack(self.archive, self.destination)
        self.assertEqual((self.destination / "keep.txt").read_text(), "keep")

    def test_unsafe_names_rejected(self):
        for name in ("../escape", "/absolute", "C:escape", "nested/file", "..\\escape", "CON.txt", "LPT1", "trailing."):
            self.malformed_archive([name])
            with self.subTest(name=name), self.assertRaises(ValueError):
                portable.inspect_archive(self.archive)

    def test_case_collisions_rejected(self):
        self.malformed_archive(["file.json", "FILE.json"])
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive)

    def test_duplicate_entries_rejected(self):
        self.malformed_archive(["same.json", "same.json"])
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive)

    def test_symlink_archive_entry_rejected(self):
        entry = zipfile.ZipInfo("linked.json")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.archive, "w") as target:
            target.writestr(entry, b"../outside")
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive)

    def test_directory_archive_entry_rejected(self):
        self.malformed_archive(["directory/"])
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive)

    def test_expanded_total_limit(self):
        self.export()
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive, portable.Limits(max_total_bytes=10))

    def test_per_file_size_limit(self):
        self.export()
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive, portable.Limits(max_file_bytes=10))

    def test_metadata_size_limit(self):
        self.export()
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive, portable.Limits(max_metadata_bytes=10))

    def test_entry_count_limit(self):
        self.export()
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive, portable.Limits(max_entries=2))

    def test_high_compression_ratio_rejected(self):
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
            target.writestr("compressed.json", b"A" * 200000)
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive)

    def test_unlisted_archive_file_rejected(self):
        self.export()
        self.rewrite_archive(extras={"extra.txt": b"not declared"})
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive)

    def test_unlisted_source_files_not_exported(self):
        (self.pack / "raw-secret.log").write_text("do not export", encoding="utf-8")
        self.export()
        with zipfile.ZipFile(self.archive) as source:
            self.assertNotIn("raw-secret.log", source.namelist())

    def test_import_has_no_transport_index_in_original_pack(self):
        self.export()
        portable.import_pack(self.archive, self.destination)
        self.assertFalse((self.destination / portable.INDEX).exists())
        self.assertEqual(len(list(self.destination.iterdir())), 6)

    def test_failed_export_cleans_temporary_file(self):
        with patch.object(portable.os, "link", side_effect=OSError("publish failed")):
            with self.assertRaises(OSError):
                self.export()
        self.assertFalse(list(self.root.glob(".pack-export-*")))
        self.assertFalse(self.archive.exists())

    def test_failed_import_publish_cleans_staging(self):
        self.export()
        with patch.object(Path, "rename", side_effect=OSError("publish failed")):
            with self.assertRaises(OSError):
                portable.import_pack(self.archive, self.destination)
        self.assertFalse(list(self.root.glob(".pack-import-*")))
        self.assertFalse(self.destination.exists())

    def test_cli_roundtrip_in_actual_processes(self):
        executable = [sys.executable, str(Path(portable.__file__))]
        for arguments in (["export", str(self.pack), "--output", str(self.archive)],
                          ["verify", str(self.archive)],
                          ["import", str(self.archive), "--destination", str(self.destination)]):
            result = subprocess.run([*executable, *arguments], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(json.loads(result.stdout)["status"], {"exported", "verified", "imported"})

    def test_cli_errors_do_not_copy_private_paths(self):
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(portable.main(["verify", str(self.root / "private-input.zip")]), 2)
        self.assertNotIn("private-input", error.getvalue())

    def test_bad_zip_is_controlled_error(self):
        self.archive.write_bytes(b"not a zip file")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(portable.main(["verify", str(self.archive)]), 2)






    def test_zip64_locator_rejected(self):
        self.export()
        data = self.archive.read_bytes()
        end = data.rfind(b"PK\x05\x06")
        self.archive.write_bytes(data[:end] + b"PK\x06\x07" + b"\x00" * 16 + data[end:])
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive)

    def test_duplicate_transport_metadata_key_rejected(self):
        self.export()
        with zipfile.ZipFile(self.archive) as source:
            original = source.read(portable.INDEX)
        modified = original.replace(b'"archive_format":1', b'"archive_format":1,"archive_format":1')
        self.assertNotEqual(original, modified)
        self.rewrite_archive(changes={portable.INDEX: modified})
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive)

    def test_encrypted_entry_flag_rejected(self):
        self.export()
        data = bytearray(self.archive.read_bytes())
        local = data.find(b"PK\x03\x04")
        central = data.find(b"PK\x01\x02")
        for offset in (local + 6, central + 8):
            flags = struct.unpack_from("<H", data, offset)[0]
            struct.pack_into("<H", data, offset, flags | 1)
        self.archive.write_bytes(data)
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive)

    def test_preflight_rejects_declared_directory_overflow(self):
        self.export()
        data = bytearray(self.archive.read_bytes())
        end = data.rfind(b"PK\x05\x06")
        struct.pack_into("<L", data, end + 12, 1000000)
        self.archive.write_bytes(data)
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive)

    def test_preflight_rejects_split_archive(self):
        self.export()
        data = bytearray(self.archive.read_bytes())
        end = data.rfind(b"PK\x05\x06")
        struct.pack_into("<H", data, end + 4, 1)
        self.archive.write_bytes(data)
        with self.assertRaises(ValueError):
            portable.inspect_archive(self.archive)
