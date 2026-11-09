# WS75 Quadro RTX 4000 — development and deferred validation

**Branch:** \`feature/quadro-rtx-4000-support\`  
**Upstream:** NullMoth \`nvidia-macos-driver\`, based on upstream \`main\`.

## Known hardware (historical inventory, not a live macOS measurement)

| Function | PCI ID | Location | ACPI |
| --- | --- | --- | --- |
| Quadro RTX 4000 Max-Q | 10DE:1EB6, subsystem 1462:12B0, rev A1 | 01:00.0 | \`\\_SB.PCI0.PEG0.PEGP\` |
| NVIDIA HD audio | 10DE:10F8 | 01:00.1 | Same multifunction device |
| NVIDIA USB controller | 10DE:1AD8 | 01:00.2 | NXHC |
| NVIDIA USB-C controller | 10DE:1AD9 | 01:00.3 | Multifunction device |
| Intel UHD Graphics | 8086:9BC4 | 00:02.0 | \`\\_SB.PCI0.GFX0\` |

**Do not confuse PCI function 01:00.1/2/3 with additional GPUs.** They may affect root-port ownership, bridge forwarding and power transitions.

## Source-level findings

1. The generic \`NVRM\` IOKit personality matches NVIDIA display-class devices. The RM support gates remain authoritative; do not special-case \`1EB6\` to bypass them.
2. \`1EB6\` is present in the installer's supported ID table.
3. \`nvrmIsTuringDeviceId()\` includes \`1EB6\`; the Turing path currently uses a 10-second settle interval when BAR1 was placed.
4. \`placeLargeBar1()\` includes logic for small Turing apertures, root-port bus-range occupancy, and preserving an already usable BAR1. A laptop with NVIDIA audio/USB/USB-C functions needs particularly careful review before moving bridge windows. Do not override the sibling-device safety check.
5. GSP success requires \`rm_init_adapter()\` to complete and emit the \`PASS 2 REACHED\` message. This does **not** demonstrate display routing or Metal.
6. Historical ACPI summaries identify \`SaSsdt\` display methods and \`PegSsdt\` PCIe methods, but full method bodies and connector wiring remain unverified.

## Pending source and hardware research

- Determine exact TU10x implementation and shader compiler selection from runtime reports; don't infer TU106 solely from marketing name.
- Confirm GSP firmware branch and exact files expected by the build, including matching RM/GSP versions and checksum provenance.
- Confirm BAR0/BAR1/BAR3 addresses, sizes, resizable-BAR capabilities and root-port secondary/subordinate bus ranges. Do not assume desktop ReBAR behavior on this notebook.
- Determine whether the internal panel, HDMI, miniDP and USB-C outputs are routed to Intel or NVIDIA; ACPI method names alone do not establish wiring.
- Confirm whether the macOS PCI registry exposes the NVIDIA device while the current \`-wegnoegpu\` boot argument is active.
- Assess sleep/wake, NVIDIA audio and USB-C function dependencies before enabling GPU power transitions.

## Deferred testing sequence (not authorized to change the live EFI)

1. **CPU-only source checks:** \`python3 tools/test_ws75_quadro.py\`, \`python3 tools/test_ws75_gsp_triage.py\`; macOS-only upstream \`python3 tools/test_card_support.py\`.
2. **Build-only:** compile all kernel extensions and plugin components against the selected macOS 26 SDK; record build hashes and warnings.
3. **Read-only inventory:** collect a redacted PCI tree, IOKit GPU path, firmware table extracts and boot configuration. Keep the original working EFI untouched.
4. **Reversible lab boot (separate approval required):** verify independent recovery media and an EFI backup; document recovery procedure; only then review any driver activation, \`-wegnoegpu\`, SIP, AMFI or SecureBootModel changes.
5. **Hardware milestones:** PCI claim → RM gate → GSP firmware request → MSI → \`rm_init_adapter\` → framebuffer → external displays → Metal render. Stop on the first failing milestone.

## Diagnostic interpretation

Run \`python3 tools/ws75_gsp_triage.py path/to/redacted-kernel.log\` only after a log is available. The analyzer reports the **last detected PCI-probe segment**, not a claim that a specific boot succeeded. Some partial logs lack a probe marker and cannot reliably separate boots. The tool does not validate firmware files or hardware.

## Security and upstream attribution

This is experimental development based on NullMoth's upstream driver. Retain upstream notices and component licenses. Do not commit firmware binaries, private ACPI tables containing licensing data (e.g., MSDM), machine serial numbers, private keys, or unredacted logs. No changes to the live OpenCore EFI or security settings are part of this work.
