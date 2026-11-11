#!/usr/bin/env python3
"""Build pinned NVIDIA RM/NVKMS Mach-O archives in a private source snapshot."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import lzma
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import struct
import subprocess

VERSION = '615.78.08'
COMMIT = '1a82fbfda8f321b056eb3568850f9316c5e465c5'
TARGET = 'x86_64-apple-macos15.0'
HERE = Path(__file__).resolve().parent
PATCHES = (
    ('615-darwin-version.patch', None),
    ('615-timer-handle-clear.patch', None),
    ('615-display-completion.patch', None),
    ('610-setmode-reason.patch', 'src/nvidia-modeset/kapi/src/nvkms-kapi.c'),
    ('610-backlight-register-log.patch', 'src/nvidia-modeset/src/nvkms-rm.c'),
    ('615-viewport-scaling.patch', 'src/nvidia-modeset/kapi/src/nvkms-kapi.c'),
)


def llvm_tool(name):
    tool = shutil.which(name)
    if tool:
        return tool
    for directory in os.get_exec_path():
        candidates = [p for p in Path(directory).glob(name + '-[0-9]*')
                      if p.name[len(name) + 1:].isdigit() and os.access(p, os.X_OK)]
        if candidates:
            return str(max(candidates, key=lambda p: int(p.name[len(name) + 1:])))
    return None


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def macho_object(path):
    with path.open('rb') as stream:
        header = stream.read(16)
    return len(header) == 16 and struct.unpack('<4I', header) == (0xfeedfacf, 0x01000007, 3, 1)


def validate_source(vendor):
    head = subprocess.check_output(['git', '-C', str(vendor), 'rev-parse', 'HEAD'], text=True).strip()
    if head != COMMIT:
        raise ValueError(f'NVIDIA source must be {VERSION} commit {COMMIT}, got {head}')
    run(['git', '-C', vendor, 'diff', '--quiet', 'HEAD', '--'])
    # Reject untracked source additions too; the build must come from the pinned snapshot.
    untracked = subprocess.check_output(['git', '-C', str(vendor), 'ls-files', '--others', '--exclude-standard'], text=True)
    if untracked.strip():
        raise ValueError('NVIDIA checkout has untracked files; use a clean clone')


def apply_patches(source):
    proof = {}
    for name, relative in PATCHES:
        patch = HERE.parent / 'kexts/NVRM/patches' / name
        if relative is None:
            args = ['patch', '--batch', '--forward', '--fuzz=0', '-p1', '-i', patch]
        else:
            args = ['patch', '--batch', '--forward', '--fuzz=0', source / relative, patch]
        run(args, cwd=source)
        proof[name] = sha256(patch)
    return proof


def compile_plan(module, compiler, make):
    """Ask vendor make for each translation unit, retaining per-object flags."""
    extra = module / '_out/ws75-objects.mk'
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text('SHADER_OBJS :=\n.PHONY: ws75-objects\nws75-objects: $(call BUILD_OBJECT_LIST,$(ALL_SRCS))\n')
    result = run([make, '--no-print-directory', '-n', '-f', 'Makefile', '-f', extra,
                  'TARGET_OS=Darwin', 'TARGET_ARCH=x86_64', f'CC={compiler}', f'CXX={compiler}++',
                  'NV_VERBOSE=1', 'NV_AUTO_DEPEND=0', 'NV_BUILD_USER=builder', 'NV_BUILD_HOST=local',
                  'ws75-objects'], cwd=module, capture_output=True, text=True)
    (module / '_out/vendor-plan.txt').write_text(result.stdout)
    commands = []
    for line in result.stdout.replace('\\\n', ' ').splitlines():
        tokens = shlex.split(line)
        if not tokens or tokens[0] not in (compiler, compiler + '++') or '-c' not in tokens:
            continue
        if any(token in ('&&', ';', '|', '>', '>>') for token in tokens):
            raise ValueError('unexpected shell operator in vendor compile command')
        src = tokens[tokens.index('-c') + 1]
        output = module / '_out/Darwin_x86_64/objects' / f'{len(commands):04d}_{Path(src).stem}.o'
        tokens[tokens.index('-o') + 1] = str(output)
        tokens += ['-target', TARGET, '-DNV_UNIX', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables']
        commands.append({'directory': str(module), 'file': src, 'output': str(output), 'arguments': tokens})
    if not commands:
        raise ValueError(f'no compile commands extracted for {module.name}')
    return commands


def shader_plan(module, compiler):
    commands = []
    out = module / '_out/Darwin_x86_64'
    for arch in ('turing', 'ampere', 'hopper', 'blackwell', 'gb20x'):
        data = (module / 'src/shaders' / f'g_{arch}_shaders').read_bytes()
        compressed = lzma.compress(data, format=lzma.FORMAT_XZ, check=lzma.CHECK_NONE,
                                   preset=6 | lzma.PRESET_EXTREME)
        blob = out / f'{arch}_shaders.xz'
        blob.write_bytes(compressed)
        assembly = out / f'{arch}_shaders.S'
        start = f'__binary_{arch}_shaders_xz_start'
        end = f'__binary_{arch}_shaders_xz_end'
        assembly.write_text(f'.section __TEXT,__const\n.p2align 4\n.globl {start}\n{start}:\n'
                            f'.incbin "{blob}"\n.globl {end}\n{end}:\n')
        output = out / 'objects' / f'shader_{arch}.o'
        commands.append({'directory': str(module), 'file': str(assembly), 'output': str(output),
                         'arguments': [compiler, '-target', TARGET, '-c', str(assembly), '-o', str(output)]})
    return commands


def compile_one(command):
    output = Path(command['output'])
    output.parent.mkdir(parents=True, exist_ok=True)
    log = output.with_suffix('.log')
    with log.open('w') as stream:
        result = subprocess.run(command['arguments'], cwd=command['directory'], stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode or not macho_object(output):
        raise RuntimeError(f'compile failed: {command["file"]}; see {log}')


def archive_objects(archive, objects, archiver, cross):
    prefix = [archiver] + (['--format=darwin'] if cross else [])
    for offset in range(0, len(objects), 100):
        run(prefix + ['rc', str(archive)] + objects[offset:offset + 100])
    run(prefix + ['s', str(archive)])


def build(vendor, output, jobs, cross=False):
    validate_source(vendor)
    if not re.fullmatch(r'[/A-Za-z0-9_.@+\-]+', str(output)):
        raise ValueError('choose an output path without spaces or shell metacharacters (vendor make limitation)')
    if output == vendor or output.is_relative_to(vendor) or vendor.is_relative_to(output):
        raise ValueError('output and vendor source must be separate directories')
    if output.exists() and any(output.iterdir()):
        raise ValueError('output directory must be empty; failed builds retain logs for inspection')
    if not cross and platform.system() != 'Darwin':
        raise ValueError('full native archive builds require macOS; use --cross-archives for LLVM verification on Linux')
    if cross:
        compiler = shutil.which('clang')
        archiver = llvm_tool('llvm-ar')
    else:
        compiler = subprocess.check_output(['xcrun', '--find', 'clang'], text=True).strip()
        archiver = subprocess.check_output(['xcrun', '--find', 'ar'], text=True).strip()
    make = shutil.which('gmake') or shutil.which('make')
    if not compiler or not archiver or not make:
        raise ValueError('clang, GNU make, and a Darwin-capable archiver are required')
    output.mkdir(parents=True, exist_ok=True)
    source = output / 'vendor'
    # Export tracked files only; do not copy ignored build outputs or modify the original tree.
    archive = subprocess.Popen(['git', '-C', str(vendor), 'archive', COMMIT], stdout=subprocess.PIPE)
    source.mkdir()
    try:
        run(['tar', '-x', '-C', source], stdin=archive.stdout)
    finally:
        archive.stdout.close()
        status = archive.wait()
    if status:
        raise RuntimeError('git archive failed')
    patches = apply_patches(source)
    manifest = {'version': VERSION, 'source_commit': COMMIT, 'target': TARGET,
                'cross_archives': cross, 'patches': patches, 'archives': {}, 'objects': {}, 'inputs': {}}
    for name, filename, symbol, label in (
        ('nvidia', 'libnvkernel.a', 'NVRM_ID', 'UNIX Open Kernel Module'),
        ('nvidia-modeset', 'libnvkms.a', 'NV_KMS_ID', 'UNIX Open Kernel Mode Setting Driver'),
    ):
        module = source / 'src' / name
        out = module / '_out/Darwin_x86_64'
        out.mkdir(parents=True, exist_ok=True)
        (out / 'version.h').write_text(f'#define NVIDIA_VERSION "{VERSION}"\n')
        (out / 'g_nvid_string.c').write_text(
            f'const char {symbol}[] = "nvidia id: NVIDIA {label} for x86_64 {VERSION} Release Build";\n'
            f'const char *const p{symbol} = {symbol} + 11;\n')
        commands = compile_plan(module, compiler, make)
        if name == 'nvidia-modeset':
            commands += shader_plan(module, compiler)
        (out / 'compile_commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        (out / 'compile_cmds.sh').write_text('\n'.join(shlex.join(c['arguments']) for c in commands) + '\n')
        print(f'{name}: compiling {len(commands)} Mach-O objects with {jobs} workers', flush=True)
        failures = []
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = [pool.submit(compile_one, command) for command in commands]
            for index, future in enumerate(as_completed(futures), 1):
                try:
                    future.result()
                except (OSError, RuntimeError) as exc:
                    failures.append(str(exc))
                if index % 100 == 0:
                    print(f'{name}: {index}/{len(commands)} completed', flush=True)
        if failures:
            (out / 'failures.txt').write_text('\n'.join(failures) + '\n')
            raise RuntimeError(f'{len(failures)} compile failures; see {out / "failures.txt"}')
        objects = [c['output'] for c in commands]
        library = out / filename
        archive_objects(library, objects, archiver, cross)
        manifest['archives'][str(library.relative_to(output))] = sha256(library)
        manifest['objects'].update({str(Path(o).relative_to(output)): sha256(Path(o)) for o in objects})
    # Bind the later XNU compile to the same headers and command plans as these archives.
    for path in source.rglob('*'):
        relative = path.relative_to(source)
        if path.is_file() and '_out' not in relative.parts:
            manifest['inputs'][str(path.relative_to(output))] = sha256(path)
    for module in ('nvidia', 'nvidia-modeset'):
        out = source / 'src' / module / '_out/Darwin_x86_64'
        for name in ('compile_commands.json', 'version.h', 'g_nvid_string.c'):
            path = out / name
            manifest['inputs'][str(path.relative_to(output))] = sha256(path)
    manifest['compiler'] = subprocess.check_output([compiler, '--version'], text=True).splitlines()[0]
    (output / 'darwin-build-proof.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Paired Darwin archives built; proof: {output / "darwin-build-proof.json"}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', type=Path, required=True, help=f'clean NVIDIA {VERSION} Git checkout')
    parser.add_argument('--output', type=Path, required=True, help='empty private build directory; no spaces')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--cross-archives', action='store_true', help='Linux LLVM Mach-O archive verification; no kext link')
    args = parser.parse_args()
    if not 1 <= args.jobs <= 64:
        parser.error('--jobs must be between 1 and 64')
    try:
        build(args.vendor.resolve(), args.output.resolve(), args.jobs, args.cross_archives)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'build error: {exc}\n')


if __name__ == '__main__':
    main()
