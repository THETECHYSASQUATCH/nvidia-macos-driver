#!/usr/bin/env python3
"""Build matched NVRM/display kexts into a private folder; never install them."""
import argparse
import json
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys

from build_darwin_archives import COMMIT, TARGET, VERSION, sha256

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'kexts/NVRM'
CPP_SOURCES = (
    'NVRM.cpp', 'os-xnu.cpp', 'os-xnu2.cpp', 'os-nvkms-xnu.cpp',
    'nv_xnu_power.cpp', 'nv_xnu_stubs.cpp', 'nvrm_fbinfo.cpp',
    'nvrm_gpuva.cpp', 'nvrm_surfshare.cpp',
)


def read_archives(base):
    proof = json.loads((base / 'darwin-build-proof.json').read_text())
    if proof.get('source_commit') != COMMIT or proof.get('version') != VERSION or proof.get('target') != TARGET:
        raise ValueError('archives do not match the pinned vendor version and target')
    inputs = proof.get('inputs')
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError('archive proof lacks source/header/command-plan hashes; rebuild the archives')
    for relative, expected in inputs.items():
        path = (base / relative).resolve()
        if not path.is_relative_to(base.resolve()) or sha256(path) != expected:
            raise ValueError(f'archive build input changed: {relative}')
    libraries = []
    for module, name in (('nvidia', 'libnvkernel.a'), ('nvidia-modeset', 'libnvkms.a')):
        relative = f'vendor/src/{module}/_out/Darwin_x86_64/{name}'
        library = base / relative
        if proof.get('archives', {}).get(relative) != sha256(library):
            raise ValueError(f'archive hash mismatch: {library}')
        libraries.append(library)
    return libraries


def vendor_commands(base, module):
    return json.loads((base / f'vendor/src/{module}/_out/Darwin_x86_64/compile_commands.json').read_text())


def command_for(commands, suffix):
    matches = [entry for entry in commands if entry['file'].endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f'expected one vendor compile command for {suffix}, found {len(matches)}')
    return matches[0]


def include_and_define_flags(entry):
    """Carry vendor ABI definitions/includes into the XNU C++ translation units."""
    arguments = entry['arguments']
    flags = []
    index = 1
    while index < len(arguments):
        token = arguments[index]
        if token == '-I':
            index += 1
            flags += ['-I', str((Path(entry['directory']) / arguments[index]).resolve())]
        elif token.startswith('-I'):
            flags += ['-I', str((Path(entry['directory']) / token[2:]).resolve())]
        elif token.startswith('-D') and token not in ('-DNVRM', '-D_LANGUAGE_C'):
            flags.append(token)
        index += 1
    return flags


def replace_source(entry, source, output, compiler, local_include):
    args = list(entry['arguments'])
    args[0] = compiler
    args[args.index('-c') + 1] = str(source)
    args[args.index('-o') + 1] = str(output)
    args += ['-I', str(local_include)]
    return {'directory': entry['directory'], 'arguments': args, 'output': str(output)}


def make_plan(base, output, sdk, compiler):
    libraries = read_archives(base)
    for header in ('nvrm_vram_abi.h', 'nvrm_gpuva_abi.h'):
        if sha256(SRC / header) != sha256(ROOT / 'kexts/NVRMFB' / header):
            raise ValueError(f'NVRM/NVRMFB shared ABI header mismatch: {header}')
    rm = command_for(vendor_commands(base, 'nvidia'), 'arch/nvalloc/unix/src/osapi.c')
    kms = command_for(vendor_commands(base, 'nvidia-modeset'), 'kapi/src/nvkms-kapi.c')
    headers = sdk / 'System/Library/Frameworks/Kernel.framework/Headers'
    flags = [
        '-target', TARGET, '-isysroot', str(sdk), '-fapple-kext', '-mkernel', '-nostdinc',
        '-I', str(headers), '-I', str(SRC),
        '-DKERNEL', '-DKERNEL_PRIVATE', '-DDRIVER_PRIVATE', '-DAPPLE', '-DNeXT',
        '-std=c++17', '-fno-rtti', '-fno-exceptions', '-fno-builtin', '-fno-common',
        '-fno-stack-protector', '-mno-red-zone', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
        '-Wall', '-Wno-unused-parameter', '-Wno-inconsistent-missing-override',
        '-Wno-unused-function', '-O2',
    ] + include_and_define_flags(rm)
    # Both components need KMS headers, but RM's ABI definitions remain authoritative.
    kms_flags = include_and_define_flags(kms)
    for index, token in enumerate(kms_flags):
        if index and kms_flags[index - 1] == '-I':
            flags += ['-I', token]
    # os-nvkms-xnu.cpp implements this interface, so the local header must precede vendor headers.
    commands = []
    nvrm_objects = []
    for name in CPP_SOURCES:
        obj = output / 'objects' / (Path(name).stem + '.o')
        nvrm_objects.append(obj)
        commands.append({'directory': str(ROOT), 'output': str(obj),
                         'arguments': [compiler + '++'] + flags + ['-c', str(SRC / name), '-o', str(obj)]})
    for name, entry in (('nvrm_pageoff.c', rm), ('nvrm_kapi_fields.c', kms)):
        obj = output / 'objects' / (Path(name).stem + '.o')
        nvrm_objects.append(obj)
        commands.append(replace_source(entry, SRC / name, obj, compiler, SRC))
    bundles = []
    components = [('NVRM', nvrm_objects, SRC / 'Info.plist', libraries)]
    for name, directory, filename in (
        ('NVRMFB', ROOT / 'kexts/NVRMFB/fb', 'nvrm-fb.cpp'),
        ('NVRMAGDC', SRC / 'agdc', 'nvrm-agdc.cpp'),
    ):
        obj = output / 'objects' / f'{name}.o'
        commands.append({'directory': str(ROOT), 'output': str(obj),
                         'arguments': [compiler + '++'] + flags + ['-I', str(directory), '-c', str(directory / filename), '-o', str(obj)]})
        components.append((name, [obj], directory / 'Info.plist', []))
    # Build the paired accelerators directly so this entry point has no dependence on upstream home paths.
    for major in (15, 26):
        obj = output / 'objects' / f'NVAccel-{major}.o'
        accel_flags = flags + ['-I', str(SRC / 'accel'), '-I', str(SRC / 'accel/iofam'), '-I', str(SRC / 'accel/re')]
        if major == 26:
            accel_flags += ['-DNM_TAHOE']
        commands.append({'directory': str(ROOT), 'output': str(obj),
                         'arguments': [compiler + '++'] + accel_flags + ['-c', str(SRC / 'accel/nvrm-accel.cpp'), '-o', str(obj)]})
        components.append((f'{major}/NVAccel', [obj], SRC / 'accel/Info.plist', []))
    for name, objects, plist, archives in components:
        executable = name.split('/')[-1]
        bundle = output / f'{name}.kext'
        binary = bundle / 'Contents/MacOS' / executable
        commands.append({'directory': str(ROOT), 'output': str(binary), 'arguments': [compiler + '++',
                         '-target', TARGET, '-isysroot', str(sdk), '-fapple-kext', '-nostdlib',
                         '-Xlinker', '-kext'] + [str(o) for o in objects] + [str(a) for a in archives] +
                        ['-lkmodc++', '-lkmod', '-lcc_kext', '-o', str(binary)]})
        bundles.append({'binary': str(binary), 'plist_source': str(plist), 'bundle': str(bundle)})
    return {'vendor_version': VERSION, 'source_commit': COMMIT, 'target': TARGET,
            'build_verified': False, 'activation': 'deferred', 'commands': commands, 'bundles': bundles}


def verify_kext(binary):
    # The object check in the archive builder deliberately requires MH_OBJECT;
    # final bundles must instead be x86_64 Mach-O kext bundles (MH_KEXT_BUNDLE = 11).
    import struct
    with binary.open('rb') as stream:
        header = stream.read(16)
    return len(header) == 16 and struct.unpack('<4I', header) == (0xfeedfacf, 0x01000007, 3, 11)


def local_inputs():
    inputs = {}
    for directory in (SRC, ROOT / 'kexts/NVRMFB'):
        for path in directory.rglob('*'):
            if path.is_file():
                inputs[str(path.relative_to(ROOT))] = sha256(path)
    topology = ROOT / 'kexts/NMHDA/nmhda_topology.h'
    inputs[str(topology.relative_to(ROOT))] = sha256(topology)
    return inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives', required=True, type=Path, help='output of build_darwin_archives.py')
    parser.add_argument('--output', required=True, type=Path, help='empty private build folder')
    parser.add_argument('--sdk', type=Path, help='selected macOS SDK; normally resolved by xcrun')
    parser.add_argument('--plan-only', action='store_true', help='write a command plan without compiling or linking')
    args = parser.parse_args()
    try:
        base, output = args.archives.resolve(), args.output.resolve()
        if output == base or output.is_relative_to(base) or base.is_relative_to(output):
            raise ValueError('kext output and archive build must be separate directories')
        if output == ROOT or ROOT.is_relative_to(output) or output.is_relative_to(SRC):
            raise ValueError('use a separate build folder, outside the kext sources')
        if output.exists() and any(output.iterdir()):
            raise ValueError('output must be empty; old artifacts cannot count as a new build')
        if not args.plan_only and platform.system() != 'Darwin':
            raise ValueError('a complete kext compile/link requires macOS with Xcode')
        sdk = args.sdk.resolve() if args.sdk else Path(subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip())
        if not (sdk / 'System/Library/Frameworks/Kernel.framework/Headers').is_dir():
            raise ValueError(f'Kernel.framework headers missing from {sdk}')
        compiler = '/usr/bin/clang' if args.plan_only else subprocess.check_output(['xcrun', '--find', 'clang'], text=True).strip()
        plan = make_plan(base, output, sdk, compiler)
        inputs = local_inputs()
        plan['source_inputs'] = inputs
        output.mkdir(parents=True, exist_ok=True)
        (output / 'build-plan.json').write_text(json.dumps(plan, indent=2) + '\n')
        if args.plan_only:
            print(f'Plan only; no binaries built: {output / "build-plan.json"}')
            return 0
        for index, command in enumerate(plan['commands']):
            target = Path(command['output'])
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f'Building {target.name}', flush=True)
            with (output / f'{index:02d}-{target.name}.log').open('w') as log:
                subprocess.run(command['arguments'], cwd=command['directory'], stdout=log, stderr=subprocess.STDOUT, check=True)
        if local_inputs() != inputs:
            raise ValueError('source files changed during the build; use a stable checkout and rebuild')
        artifacts = {}
        for bundle in plan['bundles']:
            binary = Path(bundle['binary'])
            if not verify_kext(binary):
                raise ValueError(f'not an x86_64 Mach-O kext: {binary}')
            plist = Path(bundle['plist_source'])
            with plist.open('rb') as stream:
                info = plistlib.load(stream)
            if info['CFBundleExecutable'] != binary.name:
                raise ValueError(f'plist executable mismatch: {plist}')
            destination = Path(bundle['bundle']) / 'Contents/Info.plist'
            shutil.copyfile(plist, destination)
            artifacts[str(binary.relative_to(output))] = sha256(binary)
            artifacts[str(destination.relative_to(output))] = sha256(destination)
        proof = {'build_verified': True, 'activation': 'deferred', 'target': TARGET,
                 'vendor_source_commit': COMMIT, 'artifacts': artifacts, 'source_inputs': inputs,
                 'archive_proof_sha256': sha256(base / 'darwin-build-proof.json'),
                 'source_revision': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
                 'source_dirty': bool(subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain'], text=True).strip()),
                 'sdk': str(sdk), 'compiler': subprocess.check_output([compiler, '--version'], text=True).splitlines()[0]}
        (output / 'kext-build-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
        print(f'Build-only artifacts complete: {output}; no installation or activation performed')
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'build error: {exc}\n')


if __name__ == '__main__':
    sys.exit(main())
