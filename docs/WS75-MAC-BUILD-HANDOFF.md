# WS75 Mac build handoff

The current branch is **offline-tested, not a verified complete Mac build**.
Hardware activation remains deferred. No EFI or security-setting changes are
needed to run the source tests or compile artifacts into a private build folder.

## Source baseline

Use `feature/quadro-rtx-4000-support`. The target remains the MSI WS75 10TL,
TU104GLM Quadro RTX 4000 Max-Q, PCI ID `10DE:1EB6`. The generic RM support gates
remain authoritative. BAR1 relocation now refuses other PCI functions on the GPU
bus, including the WS75 audio/USB/USB-C siblings; preserving their window takes
priority over relocation. This can leave the existing small-BAR fallback active.

The firmware loader clears both caller outputs before processing a request and
leaves them cleared on every failure. Successful loads transfer the allocated
buffer to RM until `nv_put_firmware()`. The offline test compiles the actual
loader against synthetic VFS/allocation/digest functions. It checks cleanup and
refusal paths and rejects the original stale-output behavior as a negative
control. It does not exercise the Apple VFS or actual NVIDIA signatures.

## Checks to run now

```sh
python3 tools/test_ws75_offline.py
```

The 11 suites cover PCI personalities, RM support gates, GSP log segmentation,
firmware hash/path auditing, firmware-load failure cleanup, PCI multifunction
occupancy, scanout limits, copy-class selection, BAR1 sizing/budgets and Turing
settle timing. The copy-class check uses its embedded RM snapshot unless its
optional vendor-tree input is present. The GitHub workflow runs this same gate
on development-branch pushes and manual dispatch; it never activates a driver.

On a Mac with Xcode command line tools, also run:

```sh
python3 tools/test_card_support.py
```

That additional suite uses Apple frameworks, so it was not run on Ubuntu.

## Complete build prerequisites still missing

The public NVIDIA source baseline was independently fetched and inspected:

- Tag: `615.78.08`
- Peeled source commit: `1a82fbfda8f321b056eb3568850f9316c5e465c5`
- Source: <https://github.com/NVIDIA/open-gpu-kernel-modules/tree/615.78.08>

A clone of that tag alone does **not** provide the inputs used by this checkout's
existing scripts:

- `src/nvidia/_out/Darwin_x86_64/compile_cmds.sh`
- `src/nvidia/_out/Darwin_x86_64/libnvkernel.a`
- `src/nvidia-modeset/_out/Darwin_x86_64/compile_cmds.sh`
- `src/nvidia-modeset/_out/Darwin_x86_64/libnvkms.a`
- The complete `build-nvrm.sh` recipe referenced by `kexts/NVRM/rmcc.py`.

The public makefiles produce relocatable kernel objects using GNU linker scripts
and options; setting `TARGET_OS=Darwin` alone is not a complete Mach-O/archive
build recipe. The checkout's `build-completion-archive.py` explicitly targets
610.57.04 and stamps that version into its metadata. Do not use it to manufacture
a supposedly paired 615 archive without porting and validating the patches and
metadata. Firmware identity checks do not prove the RM and NVKMS archives match.

These missing build steps must be recovered from the upstream build environment
or reconstructed and validated on macOS. No placeholder library or unverified
linker recipe has been substituted. Existing plugin/NVK build scripts also use
upstream-specific home-directory paths; they are not a one-command clean-machine
build system.

## Read-only Mac preflight

```sh
python3 tools/ws75_build_preflight.py \
  --vendor /absolute/path/to/prepared-nvidia-615.78.08 \
  --nvrm-builder /absolute/path/to/build-nvrm.sh
```

This checks host tools, Kernel.framework headers, vendor version and required
file presence. It runs no supplied build script and writes no system files. Exit
1 means inputs are missing; exit 0 means the checked inputs exist, **not** that
they are authentic, ABI-compatible or successfully built. The JSON always leaves
`build_verified` false. No NVIDIA firmware is downloaded or installed by it.

After the build recipe is available, compile the matched NVRM/NVRMFB/NVAccel
components from one revision and record compiler/SDK versions, logs and artifact
SHA-256 hashes. Rebuild both supported NVAccel variants whenever shared ABIs
change. A successful full Mac compile/link is the next required verification;
only then assess separate hardware validation. ACPI method bodies, connector
routing and sibling power dependencies remain unverified.
