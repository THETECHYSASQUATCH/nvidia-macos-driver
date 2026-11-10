#!/usr/bin/env python3
"""Exercise the actual firmware loader with fake VFS, allocation, and digests.

No real firmware, kernel headers, installed drivers, or GPU access required.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FirmwareLoaderTests(unittest.TestCase):
    def test_loader_failure_and_ownership(self):
        source = (ROOT / 'kexts/NVRM/os-xnu2.cpp').read_text()
        begin = source.index('const void *NV_API_CALL nv_get_firmware(')
        end = source.index('\nstruct os_wait_queue ', begin)
        loader = source[begin:end]
        program = r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
using NvU32 = uint32_t; using NvU64 = uint64_t;
struct nv_state_t {};
using nv_firmware_type_t = int; using nv_firmware_chip_family_t = int;
using vfs_context_t = int; using vnode_t = void *; using caddr_t = char *;
struct vnode_attr { uint64_t va_data_size; };
#define NV_API_CALL
#define NV_XNU_FW_MAX_BYTES (256u * 1024u * 1024u)
#define FREAD 1
#define UIO_READ 1
#define UIO_SYSSPACE 1
#define IO_NODELOCKED 1
#define VATTR_INIT(v) ((void)0)
#define VATTR_WANTED(v, field) ((void)0)
#define kprintf(...) ((void)0)
#define TRC ((void)0)
static int openError, attrError, readError, residual;
static bool allocationFails, digestOK, knownImage;
static uint64_t imageSize;
static int opens, closes, allocations, frees, reads;
static char buffer;
struct nv_xnu_fw_expected { const char *name; NvU64 bytes; const char *sha1; };
static nv_xnu_fw_expected expected = {"synthetic.bin", 4, "synthetic"};
static const char *nv_xnu_fw_path(int type, int family) {
    return type == 0 && family == 0 ? "synthetic.bin" : "";
}
static const nv_xnu_fw_expected *nv_xnu_fw_expect(const char *) { return knownImage ? &expected : nullptr; }
static bool nv_xnu_fw_digest_ok(const nv_xnu_fw_expected *, const void *, size_t) { return digestOK; }
static int vfs_context_current() { return 0; }
static int vfs_context_ucred(int) { return 0; }
static int vfs_context_proc(int) { return 0; }
static int vnode_open(const char *, int, int, int, vnode_t *vp, int) {
    ++opens; *vp = &buffer; return openError;
}
static int vnode_getattr(vnode_t, vnode_attr *attr, int) { attr->va_data_size = imageSize; return attrError; }
static int vnode_close(vnode_t, int, int) { ++closes; return 0; }
static void *kern_os_malloc(size_t) { if (allocationFails) return nullptr; ++allocations; return &buffer; }
static void kern_os_free(void *p) { assert(p == &buffer); ++frees; }
static int vn_rdwr(int, vnode_t, caddr_t, int size, int, int, int, int, int *resid, int) {
    assert(size > 0); ++reads; *resid = residual; return readError;
}
''' + loader + r'''
static void reset() {
    openError = attrError = readError = residual = 0;
    allocationFails = false; digestOK = knownImage = true; imageSize = 4;
    opens = closes = allocations = frees = reads = 0;
}
static void failure(int type = 0, int family = 0) {
    const void *out = &buffer; NvU32 size = 123;
    assert(nv_get_firmware(nullptr, type, family, &out, &size) == nullptr);
    assert(out == nullptr && size == 0);
    assert(allocations == frees);
    assert(closes == (opens && !openError ? 1 : 0));
}
int main() {
    reset(); failure(1); assert(opens == 0);
    reset(); failure(0,1); assert(opens == 0);
    reset(); openError = 1; failure();
    reset(); attrError = 1; failure(); assert(reads == 0);
    reset(); imageSize = 0; failure(); assert(allocations == 0);
    reset(); imageSize = uint64_t(NV_XNU_FW_MAX_BYTES) + 1; failure(); assert(allocations == 0);
    reset(); allocationFails = true; failure(); assert(reads == 0);
    reset(); readError = 1; failure(); assert(frees == 1);
    reset(); residual = 1; failure(); assert(frees == 1);
    reset(); imageSize = 3; failure(); assert(frees == 1);
    reset(); digestOK = false; failure(); assert(frees == 1);
    reset(); const void *out = &buffer; NvU32 size = 123;
    assert(nv_get_firmware(nullptr,0,0,nullptr,&size) == nullptr && size == 0);
    assert(nv_get_firmware(nullptr,0,0,&out,nullptr) == nullptr && out == nullptr);
    assert(nv_get_firmware(nullptr,0,0,nullptr,nullptr) == nullptr);
    assert(opens == 0);
    for (bool known : {true, false}) {
        reset(); knownImage = known;
        assert(nv_get_firmware(nullptr,0,0,&out,&size) == &buffer);
        assert(out == &buffer && size == 4 && closes == 1 && frees == 0);
        nv_put_firmware(out); assert(frees == 1);
        nv_put_firmware(nullptr); assert(frees == 1);
    }
}
'''
        compiler = shutil.which('clang++') or shutil.which('g++')
        self.assertIsNotNone(compiler, 'a C++ compiler is required')
        with tempfile.TemporaryDirectory() as td:
            cpp, binary = Path(td) / 'loader.cpp', Path(td) / 'loader'
            cpp.write_text('#include <initializer_list>\n' + program)
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', str(cpp), '-o', str(binary)], check=True, timeout=60)
            subprocess.run([str(binary)], check=True, timeout=10)
            # The pre-fix loader must fail this harness, rather than passing by construction.
            old_loader = loader.replace('    if (fw_buf) *fw_buf = NULL;\n', '').replace(
                '    if (fw_size) *fw_size = 0;\n', '')
            self.assertNotEqual(old_loader, loader)
            cpp.write_text('#include <initializer_list>\n' + program.replace(loader, old_loader))
            subprocess.run([compiler, '-std=c++17', str(cpp), '-o', str(binary)], check=True, timeout=60)
            result = subprocess.run([str(binary)], capture_output=True, timeout=10, cwd=td)
            self.assertNotEqual(result.returncode, 0, 'pre-fix loader unexpectedly passed')


if __name__ == '__main__':
    unittest.main(verbosity=2)
