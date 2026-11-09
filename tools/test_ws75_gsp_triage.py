#!/usr/bin/env python3
"""CPU-only regression tests for WS75 GSP log triage."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).with_name("ws75_gsp_triage.py")
spec = importlib.util.spec_from_file_location("ws75_gsp_triage", path)
triage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(triage)


class TestGspTriage(unittest.TestCase):
    def test_success_does_not_imply_display(self):
        log = "\n".join("NVRM-xnu: " + event for event in [
            "rm_is_supported_pci_device OK; RM names 10de:1eb6",
            "rm_is_supported_device OK - this chip has a HAL and a GSP",
            "PASS 1 REACHED: RM initialised, private state built, GSP firmware requested",
            "MSI 0 armed; calling rm_init_adapter()",
            "PASS 2 REACHED: the adapter is up — GSP-RM is running on the card under macOS",
        ])
        stages, failures, count = triage.analyze(log)
        self.assertTrue(all(found for _, found in stages))
        self.assertFalse(failures)
        self.assertEqual(count, 5)

    def test_adapter_failure(self):
        stages, failures, count = triage.analyze(
            "NVRM-xnu: MSI 0 armed; calling rm_init_adapter()\n"
            "NVRM-xnu: rm_init_adapter -> FAILED\n")
        self.assertEqual(count, 2)
        self.assertFalse(stages[-1][1])
        self.assertIn("GSP/adapter initialization", [name for name, _ in failures])

    def test_unrelated_logs_are_not_evidence(self):
        stages, failures, count = triage.analyze(
            "OtherDriver: rm_init_adapter -> FAILED\n")
        self.assertEqual(count, 0)
        self.assertFalse(any(found for _, found in stages))
        self.assertFalse(failures)

    def test_unsupported_device(self):
        _, failures, _ = triage.analyze(
            "NVRM-xnu: rm_is_supported_device -> 0x56: RM will not drive device 0x1eb6\n")
        self.assertIn("Unsupported RM/GSP device", [name for name, _ in failures])


    def test_separate_boot_attempts(self):
        log = (
            "NVRM-xnu: probe 10de:1eb6 class 03.00 subsystem 1462:12b0\n"
            "NVRM-xnu: PASS 2 REACHED: the adapter is up — GSP-RM is running\n"
            "NVRM-xnu: probe 10de:1eb6 class 03.00 subsystem 1462:12b0\n"
            "NVRM-xnu: rm_init_adapter -> FAILED\n"
        )
        attempts = triage.split_attempts(log)
        self.assertEqual(len(attempts), 2)
        stages, failures, _ = triage.analyze("\n".join(attempts[-1]))
        self.assertFalse(stages[-1][1])
        self.assertIn("GSP/adapter initialization", [name for name, _ in failures])

    def test_benign_bar_not_placed_is_not_a_failure(self):
        _, failures, _ = triage.analyze(
            "NVRM-xnu: bar1: no Resizable BAR capability — BAR1 left as IOPCIFamily placed it\n"
            "NVRM-xnu: bar1: BAR1 is 256 MB, console is not inside it — not placing\n"
        )
        self.assertFalse(failures)


if __name__ == "__main__":
    unittest.main(verbosity=2)
