#!/usr/bin/env python3
"""Read-only checks for the external inputs needed by the macOS NVRM build.

This does not compile, install, fetch dependencies, or activate a driver.
"""
import argparse
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

VENDOR_COMMIT = '1a82fbfda8f321b056eb3568850f9316c5e465c5'


def inspect_vendor(vendor):
    checks = []
    if vendor is None:
        return [{'name': 'NVIDIA source', 'ok': False, 'detail': 'provide --vendor with the 615.78.08 source tree'}]
    version = vendor / 'version.mk'
    text = version.read_text() if version.is_file() else ''
    match = re.search(r'^NVIDIA_VERSION\s*[:?]?=\s*(\S+)', text, re.M)
    checks.append({'name': 'NVIDIA version', 'ok': bool(match and match[1] == '615.78.08'),
                   'detail': match[1] if match else 'version.mk missing or unrecognized'})
    for relative in (
        'src/nvidia/_out/Darwin_x86_64/compile_cmds.sh',
        'src/nvidia/_out/Darwin_x86_64/libnvkernel.a',
        'src/nvidia-modeset/_out/Darwin_x86_64/compile_cmds.sh',
        'src/nvidia-modeset/_out/Darwin_x86_64/libnvkms.a',
    ):
        path = vendor / relative
        checks.append({'name': relative, 'ok': path.is_file() and path.stat().st_size > 0,
                       'detail': 'required prepared Darwin build input'})
    return checks


def inspect_host():
    checks = [{'name': 'macOS host', 'ok': platform.system() == 'Darwin',
               'detail': platform.system() + '; the driver targets x86_64'}]
    for tool in ('xcrun', 'clang++', 'python3', 'git', 'ar'):
        path = shutil.which(tool)
        checks.append({'name': tool, 'ok': path is not None, 'detail': path or 'missing'})
    if platform.system() == 'Darwin' and shutil.which('xcrun'):
        try:
            result = subprocess.run(['xcrun', '--sdk', 'macosx', '--show-sdk-path'],
                                    capture_output=True, text=True, timeout=30)
            sdk = Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None
            headers = sdk / 'System/Library/Frameworks/Kernel.framework/Headers' if sdk else None
            checks.append({'name': 'Kernel.framework headers', 'ok': bool(headers and headers.is_dir()),
                           'detail': str(headers) if headers else result.stderr.strip()})
        except (OSError, subprocess.TimeoutExpired) as exc:
            checks.append({'name': 'macOS SDK', 'ok': False, 'detail': str(exc)})
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', type=Path)
    parser.add_argument('--nvrm-builder', type=Path, help='original complete build-nvrm.sh recipe')
    args = parser.parse_args(argv)
    checks = inspect_host() + inspect_vendor(args.vendor)
    builder = args.nvrm_builder
    checks.append({'name': 'complete NVRM build recipe',
                   'ok': bool(builder and builder.is_file() and builder.stat().st_size > 0),
                   'detail': str(builder) if builder else 'build-nvrm.sh is referenced but absent from this checkout'})
    # Existence does not establish that a supplied recipe is correct or safe to run.
    inputs_present = all(check['ok'] for check in checks)
    print(json.dumps({'nvidia_source_commit': VENDOR_COMMIT,
                      'inputs_present': inputs_present, 'build_verified': False,
                      'hardware_activation': 'deferred', 'checks': checks}, indent=2))
    return 0 if inputs_present else 1


if __name__ == '__main__':
    raise SystemExit(main())
