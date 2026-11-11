# WS75 Mac build handoff

The missing RM/NVKMS archive build and NVRM kext recipes are reconstructed.
The vendor archives have been cross-built on Ubuntu as **1,330 x86_64 Mach-O
objects**. Both RM-facing local C helpers also cross-compile. The full XNU C++
compile and final kext links still require verification on your Mac with Apple's
SDK and linker. This is a build handoff, not hardware compatibility evidence.
Activation remains deferred.

## Build on the Mac

Use this repository's `feature/quadro-rtx-4000-support` branch. Requirements:
Python 3.9 or newer with `lzma`, Git, GNU make, `patch`, `tar`, and Xcode tools
selected by `xcrun`. The selected macOS SDK must contain Kernel.framework headers
and the IOGraphics/IONDRV headers used by the framebuffer. Use the SDK intended
for the macOS 26 build; the produced code targets x86_64 with minimum macOS 15.
Apple Silicon Macs can build these x86_64 artifacts; they cannot load them.

Run these commands from the repository root, without `sudo`. Choose new, empty
output directories. The vendor build output path must not contain spaces or
shell metacharacters because of NVIDIA's makefiles; the repository path may
contain spaces. Keep the generated vendor snapshot at its original build path
because its recorded commands contain absolute paths.

```sh
python3 tools/test_ws75_offline.py
python3 tools/test_card_support.py

git clone --depth 1 --branch 615.78.08 --single-branch \
  https://github.com/NVIDIA/open-gpu-kernel-modules.git "$HOME/ws75-vendor"

python3 build/build_darwin_archives.py \
  --vendor "$HOME/ws75-vendor" \
  --output "$HOME/ws75-build/vendor615" --jobs 4

python3 tools/ws75_build_preflight.py --archives "$HOME/ws75-build/vendor615"

bash build/build-nvrm.sh \
  --archives "$HOME/ws75-build/vendor615" \
  --output "$HOME/ws75-build/kexts"
```

The archive builder validates the pinned clean NVIDIA checkout and exports it
into the output directory before patching. It does not modify the original
checkout. It reuses NVIDIA's per-source include paths and definitions, replaces
the ELF aggregation with Darwin archives, and embeds freshly compressed shaders
with Mach-O start/end symbols. Object names are unique across source directories.
It retains per-object logs, both compile-command formats and
`darwin-build-proof.json` with source, header, plan, patch, object and archive
hashes. Build metadata identifies version 615.78.08 without embedding a username
or hostname.

The kext recipe verifies the paired archive and input hashes, compiles from the
current repository, and emits:

- `NVRM.kext`
- `NVRMFB.kext` from the current `kexts/NVRMFB/fb` source, not the older copy
  under `kexts/NVRM/fb`
- `NVRMAGDC.kext`
- `15/NVAccel.kext` and `26/NVAccel.kext`, using the same shared ABI headers

It records the command plan and logs, checks final Mach-O architecture/type and
plist executable names, and writes `kext-build-proof.json` only after all five
kexts compile and link. Source changes during the build invalidate the result.
No script installs, signs, loads or activates a driver or edits boot settings.
The Metal plugin, translator, Mesa/NVK and firmware packaging remain separate
upstream components; these commands reconstruct the missing **kernel build**,
not a complete distributable graphics-driver package.

A failed build leaves its logs for inspection. Use another empty output folder
for a fresh attempt; stale binaries cannot satisfy a new build. If SDK headers
are missing, select or supply the correct development SDK before retrying. Do not
replace missing headers or archives with empty stubs.

## Verification without macOS

On Linux with Clang and LLVM ar, the same vendor steps can be checked with:

```sh
python3 build/build_darwin_archives.py \
  --vendor /absolute/path/to/clean-nvidia-source \
  --output /tmp/ws75-darwin-archives --jobs 4 --cross-archives

WS75_ARCHIVE_BUILD=/tmp/ws75-darwin-archives python3 tools/test_ws75_offline.py
```

The optional integration check verifies the complete archive proof and compiles
`nvrm_pageoff.c` and `nvrm_kapi_fields.c` with the actual recorded vendor commands.
Without `WS75_ARCHIVE_BUILD`, that integration check is explicitly skipped; the
other offline tests still run, including synthetic Mach-O shader/archive checks
and refusal of changed archive/header/command-plan inputs. The GitHub workflow
runs the offline gate; it does not fetch and compile the full NVIDIA tree.

To inspect a Mac command plan without compiling, use `--plan-only --sdk
/absolute/path/to/MacOSX.sdk` with `build/build-nvrm.sh`. A plan does not count as
a verified build. `ws75_build_preflight.py` is also read-only and never executes
a supplied build recipe. Its `inputs_present` result is distinct from successful
compilation; it always leaves `build_verified` false.

## Source baseline and safeguards

NVIDIA tag `615.78.08` resolves to source commit
`1a82fbfda8f321b056eb3568850f9316c5e465c5`:
<https://github.com/NVIDIA/open-gpu-kernel-modules/tree/615.78.08>.
The new builder rejects other commits and tracked or untracked source changes.

Version-specific patches enable Darwin in the Unix version-header guards,
provide the 615 flip-completion callback and notifier reset behavior, clear a
cancelled OS-timer handle, and apply the existing mode-refusal, backlight logging
and viewport-scaling changes. NVIDIA 615 already guards and clears the FSP poll
event; the old 610 FSP patch is not applied again. The legacy
`build-completion-archive.py` remains a 610-specific tool and is not called.

The target remains TU104GLM Quadro RTX 4000 Max-Q (`10DE:1EB6`) on the MSI WS75.
RM support gates remain authoritative. BAR1 relocation refuses same-bus PCI
siblings, and firmware-load failures clear output metadata and release buffers.
No device-ID support override or firmware substitution was introduced.

ACPI method bodies, physical connector routing, sibling power dependencies and
actual GSP startup remain unverified. Complete the Mac build and review its logs
before considering a separately authorized hardware-validation phase. Ubuntu
drivers, OpenCore EFI, SIP, AMFI and Secure Boot are outside this build workflow.
