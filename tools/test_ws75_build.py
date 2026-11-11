#!/usr/bin/env python3
"""CPU-only build regressions: Mach-O generation, pairing, and Mac command plans."""
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build'))
import build_darwin_archives as archives
import build_nvrm as nvrm


class BuildTests(unittest.TestCase):
    def fixture(self, base):
        proof = {'source_commit': archives.COMMIT, 'target': archives.TARGET,
                 'version': archives.VERSION, 'archives': {}, 'inputs': {}}
        for module, library, src in (
            ('nvidia', 'libnvkernel.a', 'arch/nvalloc/unix/src/osapi.c'),
            ('nvidia-modeset', 'libnvkms.a', 'kapi/src/nvkms-kapi.c'),
        ):
            directory = base / 'vendor/src' / module
            out = directory / '_out/Darwin_x86_64'
            out.mkdir(parents=True)
            header = directory / 'include/nvfixture.h'
            header.parent.mkdir()
            header.write_text('/* synthetic ABI fixture */\n')
            lib = out / library
            lib.write_bytes(b'!<arch>\n')
            proof['archives'][str(lib.relative_to(base))] = archives.sha256(lib)
            commands = [{'directory': str(directory), 'file': src,
                         'arguments': ['clang', '-I', 'include', '-I./generated', '-DNVRM', '-D_LANGUAGE_C',
                                       '-DPORT_IS_KERNEL_BUILD=1', '-DNV_UNIX', '-target', archives.TARGET,
                                       '-std=gnu11', '-c', src, '-o', 'original.o']}]
            path = out / 'compile_commands.json'
            path.write_text(json.dumps(commands))
            for item in (header, path):
                proof['inputs'][str(item.relative_to(base))] = archives.sha256(item)
        (base / 'darwin-build-proof.json').write_text(json.dumps(proof))
        return proof

    def test_plan_builds_current_sources_and_both_accelerators(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / 'archives'
            self.fixture(base)
            plan = nvrm.make_plan(base, Path(td) / 'out with spaces', Path(td) / 'SDK', '/usr/bin/clang')
            commands = [c['arguments'] for c in plan['commands']]
            compiled = [c[c.index('-c') + 1] for c in commands if '-c' in c]
            self.assertIn(str(ROOT / 'kexts/NVRMFB/fb/nvrm-fb.cpp'), compiled)
            self.assertNotIn(str(ROOT / 'kexts/NVRM/fb/nvrm-fb.cpp'), compiled)
            self.assertNotIn(str(ROOT / 'kexts/NVRM/nvkms_shaders.cpp'), compiled)
            self.assertEqual(len(plan['bundles']), 5)
            accel = [c for c in commands if any(a.endswith('/accel/nvrm-accel.cpp') for a in c)]
            self.assertEqual(len(accel), 2)
            self.assertEqual(sum('-DNM_TAHOE' in c for c in accel), 1)
            self.assertFalse(plan['build_verified'])
            self.assertEqual(set(nvrm.CPP_SOURCES), {p.name for p in nvrm.SRC.glob('*.cpp')} - {'nvkms_shaders.cpp'})
            cxx = commands[0]
            self.assertNotIn('-DNVRM', cxx)
            self.assertNotIn('-D_LANGUAGE_C', cxx)
            self.assertIn('-DNV_UNIX', cxx)
            for flag in ('-I',):
                for index, token in enumerate(cxx[:-1]):
                    if token == flag:
                        self.assertTrue(Path(cxx[index + 1]).is_absolute())
            link = next(c for c in commands if '-kext' in c and c[-1].endswith('/MacOS/NVRM'))
            self.assertTrue(any(a.endswith('/libnvkernel.a') for a in link))
            self.assertTrue(any(a.endswith('/libnvkms.a') for a in link))

    def test_changed_archive_or_header_is_rejected(self):
        for changed in ('archive', 'header', 'commands'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                proof = self.fixture(base)
                relative = next(iter(proof['archives'])) if changed == 'archive' else next(
                    r for r in proof['inputs'] if r.endswith('nvfixture.h' if changed == 'header' else 'compile_commands.json'))
                (base / relative).write_bytes(b'modified')
                with self.assertRaises(ValueError):
                    nvrm.read_archives(base)

    def test_wrong_version_or_missing_proof_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proof = self.fixture(base)
            for version in ('610.57.04', None):
                proof['version'] = version
                (base / 'darwin-build-proof.json').write_text(json.dumps(proof))
                with self.assertRaises(ValueError):
                    nvrm.read_archives(base)

    def test_ambiguous_rm_command_is_rejected(self):
        entry = {'file': 'arch/nvalloc/unix/src/osapi.c'}
        for commands in ([], [entry, entry]):
            with self.assertRaises(ValueError):
                nvrm.command_for(commands, entry['file'])

    def test_real_macho_shaders_and_archive(self):
        compiler = shutil.which('clang')
        cross = sys.platform != 'darwin'
        archiver = archives.llvm_tool('llvm-ar') if cross else subprocess.check_output(['xcrun', '--find', 'ar'], text=True).strip()
        self.assertIsNotNone(compiler)
        self.assertIsNotNone(archiver, 'LLVM ar is required for this offline cross-build test')
        with tempfile.TemporaryDirectory() as td:
            module = Path(td) / 'module'
            shader_dir = module / 'src/shaders'
            shader_dir.mkdir(parents=True)
            (module / '_out/Darwin_x86_64').mkdir(parents=True)
            data = b'CPU-only synthetic shader fixture\x00' * 64
            for arch in ('turing', 'ampere', 'hopper', 'blackwell', 'gb20x'):
                (shader_dir / f'g_{arch}_shaders').write_bytes(data)
            commands = archives.shader_plan(module, compiler)
            for command in commands:
                archives.compile_one(command)
                blob = Path(command['file']).with_name(Path(command['file']).stem + '.xz')
                self.assertEqual(lzma.decompress(blob.read_bytes()), data)
            output = module / 'test.a'
            objects = [c['output'] for c in commands]
            archives.archive_objects(output, objects, archiver, cross)
            members = subprocess.check_output([archiver, 't', str(output)], text=True).splitlines()
            self.assertEqual(members, [Path(o).name for o in objects])
            self.assertTrue(all(archives.macho_object(Path(o)) for o in objects))
            self.assertFalse(nvrm.verify_kext(Path(objects[0])), 'MH_OBJECT must not count as a linked kext')

    @unittest.skipUnless(os.environ.get('WS75_ARCHIVE_BUILD'), 'set WS75_ARCHIVE_BUILD for the full vendor integration check')
    def test_full_vendor_archives_and_rm_helpers(self):
        base = Path(os.environ['WS75_ARCHIVE_BUILD']).resolve()
        libraries = nvrm.read_archives(base)
        proof = json.loads((base / 'darwin-build-proof.json').read_text())
        self.assertEqual(len(proof['objects']), 1330)
        compiler = shutil.which('clang')
        self.assertTrue(all(p.stat().st_size > 0 for p in libraries))
        archiver = archives.llvm_tool('llvm-ar') if sys.platform != 'darwin' else subprocess.check_output(['xcrun', '--find', 'ar'], text=True).strip()
        for library, expected_count in zip(libraries, (1100, 230)):
            members = subprocess.check_output([archiver, 't', str(library)], text=True).splitlines()
            self.assertEqual(len(members), expected_count)
            self.assertEqual(len(set(members)), expected_count, 'duplicate basenames would overwrite archive members')
        nm = archives.llvm_tool('llvm-nm') if sys.platform != 'darwin' else shutil.which('nm')
        self.assertIsNotNone(nm)
        for library, expected_symbols in zip(libraries, (
            {'_rm_init_adapter'},
            {'_GetFlipPendingStatus', '_nvKmsKapiGetFunctionsTableInternal'} |
            {f'__binary_{arch}_shaders_xz_{edge}' for arch in ('turing', 'ampere', 'hopper', 'blackwell', 'gb20x')
             for edge in ('start', 'end')},
        )):
            result = subprocess.run([nm, '-U', str(library)], capture_output=True, text=True, check=True)
            symbols = {line.split()[-1] for line in result.stdout.splitlines() if line.split()}
            self.assertTrue(expected_symbols <= symbols, f'missing archive symbols: {expected_symbols - symbols}')
        with tempfile.TemporaryDirectory() as td:
            sdk = Path(td) / 'MacOSX.sdk'
            (sdk / 'System/Library/Frameworks/Kernel.framework/Headers').mkdir(parents=True)
            output = Path(td) / 'plan only'
            subprocess.run([sys.executable, str(ROOT / 'build/build_nvrm.py'), '--archives', str(base),
                            '--output', str(output), '--plan-only', '--sdk', str(sdk)],
                           check=True, capture_output=True, text=True, timeout=60)
            self.assertEqual([p.name for p in output.iterdir()], ['build-plan.json'])
            self.assertFalse(json.loads((output / 'build-plan.json').read_text())['build_verified'])
            for name, module, suffix in (
                ('nvrm_pageoff.c', 'nvidia', 'arch/nvalloc/unix/src/osapi.c'),
                ('nvrm_kapi_fields.c', 'nvidia-modeset', 'kapi/src/nvkms-kapi.c'),
            ):
                entry = nvrm.command_for(nvrm.vendor_commands(base, module), suffix)
                output = Path(td) / (name + '.o')
                command = nvrm.replace_source(entry, nvrm.SRC / name, output, compiler, nvrm.SRC)
                archives.compile_one(command)


if __name__ == '__main__':
    unittest.main(verbosity=2)
