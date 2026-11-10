#!/usr/bin/env python3
"""Compile the actual BAR1 occupancy guard with an offline PCI registry."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MultifunctionTests(unittest.TestCase):
    def test_actual_guard(self):
        source = (ROOT / 'kexts/NVRM/NVRM.cpp').read_text()
        start = source.index('static bool nvrmBusRangeHasOtherDevices(')
        end = source.index('\nbool NVRM::placeLargeBar1()', start)
        helper = source[start:end]
        # Verify that the caller covers same-bus functions even with no reserved buses,
        # and rejects occupancy before the first configuration-space mutation.
        placement = source[end:source.index('UInt16 cmd = fPCI->configRead16(0x04);', end)]
        self.assertIn('if (nvrmBusRangeHasOtherDevices(mybus, sub, fPCI))', placement)
        program = r'''
#include <cassert>
#include <vector>
using UInt8 = unsigned char;
struct OSObject { virtual ~OSObject() = default; };
struct IOPCIDevice : OSObject {
    UInt8 bus, device, function;
    IOPCIDevice(int b, int d, int f): bus(b), device(d), function(f) {}
    UInt8 getBusNumber() { return bus; }
    UInt8 getDeviceNumber() { return device; }
    UInt8 getFunctionNumber() { return function; }
};
static std::vector<OSObject *> registry;
static bool unavailable = false;
static int releases = 0;
static int gIOServicePlane = 0, kIORegistryIterateRecursively = 0;
struct IORegistryIterator {
    unsigned index = 0;
    static IORegistryIterator *iterateOver(int, int) {
        return unavailable ? nullptr : new IORegistryIterator;
    }
    OSObject *getNextObject() { return index < registry.size() ? registry[index++] : nullptr; }
    void release() { ++releases; delete this; }
};
#define OSDynamicCast(T, e) dynamic_cast<T *>(e)
#define LOG(...) ((void)0)
''' + helper + r'''
int main() {
    IOPCIDevice gpu(1,0,0), audio(1,0,1), usb(1,0,2), usbc(1,0,3);
    IOPCIDevice downstream(5,0,0), unrelated(6,0,0), otherSlot(1,1,0);
    OSObject nonPCI;
    registry = {&gpu, &nonPCI, &unrelated};
    assert(!nvrmBusRangeHasOtherDevices(1,5,&gpu));
    for (auto sibling : {&audio, &usb, &usbc, &otherSlot}) {
        registry = {&gpu, sibling};
        assert(nvrmBusRangeHasOtherDevices(1,1,&gpu));
        assert(nvrmBusRangeHasOtherDevices(1,5,&gpu));
    }
    registry = {&gpu, &downstream};
    assert(nvrmBusRangeHasOtherDevices(1,5,&gpu));
    assert(!nvrmBusRangeHasOtherDevices(1,4,&gpu));
    assert(releases == 11);
    unavailable = true;
    assert(nvrmBusRangeHasOtherDevices(1,1,&gpu));
    assert(releases == 11);
}
'''
        compiler = shutil.which('clang++') or shutil.which('g++')
        self.assertIsNotNone(compiler, 'a C++ compiler is required')
        with tempfile.TemporaryDirectory() as td:
            cpp, binary = Path(td) / 'guard.cpp', Path(td) / 'guard'
            cpp.write_text(program)
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True, timeout=60)
            subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
