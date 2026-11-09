#!/usr/bin/env python3
"""CPU-only regression tests for WS75 firmware integrity audit."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("firmware_audit", Path(__file__).with_name("ws75_firmware_audit.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FirmwareAuditTests(unittest.TestCase):
    def test_match_and_modification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = b"synthetic test fixture, not NVIDIA firmware"
            (root / "gsp.bin").write_bytes(data)
            manifest = {"files": [{"path": "gsp.bin", "sha256": hashlib.sha256(data).hexdigest()}]}
            self.assertEqual(module.audit(root, manifest)[0]["status"], "match")
            (root / "gsp.bin").write_bytes(data + b"modified")
            self.assertEqual(module.audit(root, manifest)[0]["status"], "mismatch")

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(module.audit(Path(td), {"files": [
                {"path": "missing.bin", "sha256": "0" * 64}
            ]})[0]["status"], "missing")

    def test_parent_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                module.audit(Path(td), {"files": [
                    {"path": "../secret", "sha256": "0" * 64}
                ]})

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            (Path(td) / "link").symlink_to(Path(outside), target_is_directory=True)
            with self.assertRaises(ValueError):
                module.audit(Path(td), {"files": [
                    {"path": "link/secret", "sha256": "0" * 64}
                ]})

    def test_duplicate_entries_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            item = {"path": "same.bin", "sha256": "0" * 64}
            with self.assertRaises(ValueError):
                module.audit(Path(td), {"files": [item, item]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
