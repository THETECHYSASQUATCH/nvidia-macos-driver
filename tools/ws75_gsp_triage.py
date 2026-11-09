#!/usr/bin/env python3
"""Read-only NVRM startup log triage for the MSI WS75 Quadro RTX 4000.

Usage: python3 tools/ws75_gsp_triage.py path/to/driver-kernel-log.txt
       cat kernel.log | python3 tools/ws75_gsp_triage.py -
No hardware access, driver installation, or boot-argument changes.
"""
import argparse
from pathlib import Path
import re
import sys

STAGES = [
    ("PCI probe", r"rm_is_supported_pci_device OK"),
    ("RM support gate", r"rm_is_supported_device OK"),
    ("Firmware requested", r"PASS 1 REACHED:.*GSP firmware requested"),
    ("MSI interrupt", r"MSI \d+ armed; calling rm_init_adapter"),
    ("GSP adapter initialized", r"PASS 2 REACHED:.*GSP-RM is running"),
]
FAILURES = [
    ("Unsupported PCI device", r"rm_is_supported_pci_device says NO"),
    ("Unsupported RM/GSP device", r"rm_is_supported_device -> 0x[0-9a-f]+"),
    ("RM global initialization", r"rm_init_rm FAILED"),
    ("RM private state", r"rm_init_private_state FAILED"),
    ("MSI unavailable", r"no MSI source on the device"),
    ("GSP/adapter initialization", r"rm_init_adapter -> FAILED"),
    ("BAR1 placement", r"bar1:.*(?:FAILED|refusing|cannot|unsafe|not placing)"),
]


def analyze(log):
    lines = [line for line in log.splitlines() if "NVRM-xnu:" in line]
    # The log may contain multiple attempts. Report observable evidence, not
    # a fabricated successful boot or an inferred hardware cause.
    stages = [(name, any(re.search(pattern, line, re.I) for line in lines))
              for name, pattern in STAGES]
    failures = [(name, line.strip()) for name, pattern in FAILURES
                for line in lines if re.search(pattern, line, re.I)]
    return stages, failures, len(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", help="Kernel log file, or '-' for standard input")
    args = parser.parse_args(argv)
    if args.log == "-":
        log = sys.stdin.read()
    else:
        try:
            log = Path(args.log).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            parser.error(str(exc))
    stages, failures, count = analyze(log)
    print("WS75 NVIDIA GSP startup — read-only evidence report")
    print(f"NVRM log lines: {count}")
    for name, observed in stages:
        print(f"  {'OBSERVED' if observed else 'NOT OBSERVED'}: {name}")
    for name, line in failures:
        print(f"  FAILURE SIGNAL [{name}]: {line}")
    if not count:
        print("No NVRM lines found; this does not imply the GPU is absent.")
    elif not failures and not stages[-1][1]:
        print("No GSP adapter success observed. Log may be partial or the driver may not have started.")
    elif stages[-1][1]:
        print("GSP adapter success message observed; display output and Metal remain unverified.")
    print("This report does not change EFI, SIP, AMFI, or driver state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
