# WS75 kernel build verification — 2026-11-10
Validation host: Ubuntu. Compiler: `Ubuntu clang version 21.1.8 (6ubuntu1)`.
Vendor baseline: NVIDIA `615.78.08`, commit `1a82fbfda8f321b056eb3568850f9316c5e465c5`.
The reconstructed archive builder completed from a clean pinned checkout.
- RM: 1,100 x86_64 Mach-O objects; 1,100 distinct archive members.
- NVKMS: 230 x86_64 Mach-O objects including five regenerated shader blobs; 230 distinct archive members.
- Both `nvrm_pageoff.c` and `nvrm_kapi_fields.c` compiled using the recorded vendor flags. The latter retained two missing-prototype warnings in its compile log.
- All 12 offline suites passed with `WS75_ARCHIVE_BUILD` set, including the full vendor integration check.
- Build planner, changed-input refusal, real synthetic Mach-O shaders/archives, Python compilation and shell syntax checks passed.
- The plan-only CLI produced a plan without binaries or a verified-build proof.
- The read-only preflight accepted the archive/input hashes and in-repository recipe, and reported the expected missing macOS host/Xcode tools on Ubuntu.

Archive SHA-256 values from this compiler run (not expected to match a different Apple compiler):

- `libnvkernel.a`: `198d8670e91b3f9bc8aac35c9337e0d2932bf218761c3ce1c35468c9bdc67659`
- `libnvkms.a`: `a861d29a84c4b801b7bdf2d0f5b7ee79ed1632ddf722816706c6b9c7652db224`

`darwin-build-proof.json` records 4013 source/header/plan input hashes and all 1,330 object hashes. Generated source snapshots, logs and archives are build outputs and are not committed.

The complete XNU C++ compile, five final kext links and native Apple archiver remain unverified until the recipe runs on the Mac. No driver was installed or activated; no EFI, security setting or Ubuntu driver was changed. This evidence does not establish runtime GPU compatibility.

Follow [the Mac build handoff](WS75-MAC-BUILD-HANDOFF.md) for exact commands.

Recheck on 2026-11-11: all 12 offline suites passed again, with the optional full-vendor integration check explicitly skipped because the temporary vendor build directory was no longer present. Python compilation and shell syntax checks passed. Unified-diff context markers in the new patch files were preserved; whitespace checks for those files excluded end-of-line/EOF blank-marker diagnostics. No archive or source changes were made after the full integration run recorded above.
