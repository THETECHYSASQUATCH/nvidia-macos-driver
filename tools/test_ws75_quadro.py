#!/usr/bin/env python3
"""Read-only WS75 Quadro RTX 4000 source-contract regression checks.

Run from any OS: python3 tools/test_ws75_quadro.py
No GPU, root privileges, macOS SDK, or driver installation required.
These checks validate repository wiring, NOT runtime compatibility.
"""
from pathlib import Path
import plistlib
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
GPU_VENDOR = 0x10DE
GPU_DEVICE = 0x1EB6
GPU_SUBSYSTEM = 0x12B01462
GPU_CLASS = 0x0300


def installer_ids():
    source = (ROOT / "package/install.sh").read_text(encoding="utf-8")
    match = re.search(r'^SUPPORTED_IDS="\n(.*?)\n"$', source, re.M | re.S)
    if not match:
        raise AssertionError("installer supported-device table missing")
    return {int(token, 16) for token in match.group(1).split()}


def pci_mask_matches(value, rule):
    """Evaluate the IOPCI value&mask syntax against the 32-bit PCI match key."""
    lhs, mask = (int(piece, 16) for piece in rule.split("&"))
    return value & mask == lhs & mask


class WS75QuadroSourceContract(unittest.TestCase):
    def test_confirmed_device_is_in_installer_table(self):
        self.assertIn(GPU_DEVICE, installer_ids())

    def test_kext_pci_personality_matches_ws75(self):
        with (ROOT / "kexts/NVRM/Info.plist").open("rb") as stream:
            plist = plistlib.load(stream)
        personality = plist["IOKitPersonalities"]["NVRM"]
        # PCI matching uses device << 16 | vendor; class << 16 for 0300.
        self.assertTrue(pci_mask_matches(
            (GPU_DEVICE << 16) | GPU_VENDOR, personality["IOPCIPrimaryMatch"]))
        self.assertTrue(pci_mask_matches(
            GPU_CLASS << 16, personality["IOPCIClassMatch"]))
        # Also preserve the upstream generic 3D-controller matching path.
        self.assertTrue(pci_mask_matches(
            0x0302 << 16, personality["IOPCIClassMatch"]))

    def test_nvidia_rm_gates_remain_in_place(self):
        source = (ROOT / "kexts/NVRM/NVRM.cpp").read_text(encoding="utf-8")
        self.assertIn("rm_is_supported_pci_device(", source)
        self.assertIn("rm_is_supported_device(", source)
        self.assertRegex(source, r"if\s*\(!rm_is_supported_pci_device\(")

    def test_turing_family_includes_ws75_id(self):
        source = (ROOT / "kexts/NVRM/NVRM.cpp").read_text(encoding="utf-8")
        match = re.search(
            r"static inline bool nvrmIsTuringDeviceId\(unsigned int id\)\s*\{(.*?)\}",
            source, re.S)
        self.assertIsNotNone(match, "Turing detection helper missing")
        ranges = re.findall(r"id\s*>=\s*0x([0-9A-Fa-f]+)\s*&&\s*id\s*<=\s*0x([0-9A-Fa-f]+)", match.group(1))
        self.assertTrue(any(int(low, 16) <= GPU_DEVICE <= int(high, 16)
                            for low, high in ranges))
        self.assertIn("nvrmIsTuringDeviceId(nv->pci_info.device_id)", source)

    def test_target_inventory_is_documented(self):
        doc = (ROOT / "docs/WS75-QUADRO-RTX4000-AUDIT.md").read_text(encoding="utf-8")
        for expected in ("1EB6", "12B01462", "PEGP", "GFX0"):
            with self.subTest(expected=expected):
                self.assertIn(expected, doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
