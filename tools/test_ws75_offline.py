#!/usr/bin/env python3
"""Run the WS75 CPU-only regression gate; never load or install a driver."""
from pathlib import Path
import subprocess
import sys

TOOLS = Path(__file__).resolve().parent
TESTS = (
    'test_ws75_quadro.py',
    'test_ws75_build.py',
    'test_ws75_gsp_triage.py',
    'test_ws75_firmware_audit.py',
    'test_pcie_multifunction.py',
    'test_gsp_firmware_loader.py',
    'test_scanout_caps.py',
    'test_copy_class_selection.py',
    'test_fbclaim_match.py',
    'test_bar1_resize_choice.py',
    'test_bar1_budget.py',
    'test_turing_default_settle.py',
)


def main():
    failed = []
    for name in TESTS:
        print(f'Running {name}', flush=True)
        try:
            result = subprocess.run([sys.executable, str(TOOLS / name)], cwd=TOOLS.parent, timeout=180)
            if result.returncode:
                failed.append(name)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f'{name}: {exc}', file=sys.stderr)
            failed.append(name)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} offline suites passed', flush=True)
    if failed:
        print('Failed: ' + ', '.join(failed), file=sys.stderr)
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
