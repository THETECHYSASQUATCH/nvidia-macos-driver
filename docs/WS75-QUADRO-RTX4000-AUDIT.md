# MSI WS75 10TL — Quadro RTX 4000 compatibility audit (Step 1)

Status: **source-level audit only; hardware validation pending**. This is not a claim of working macOS GPU acceleration.

## Target system
- MSI WS75 10TL laptop; Intel Core i7-10875H (Comet Lake), NVIDIA Quadro RTX 4000 mobile (Turing).
- OpenCore, macOS 26 Tahoe x86_64, MacBookPro16,1 SMBIOS (reported target configuration).
- Current working boot configuration has `-wegnoegpu`; **leave it in place** until a backed-up, reversible test boot is ready.
- **Previously recorded Windows PCI inventory:** NVIDIA Quadro RTX 4000 with Max-Q Design, `VEN_10DE&DEV_1EB6&SUBSYS_12B01462&REV_A1`, PCI `01:00.0`, class `0300`, ACPI `\\_SB.PCI0.PEG0.PEGP`. Intel UHD Graphics is `8086:9BC4` at `00:02.0` (`\\_SB.PCI0.GFX0`). NVIDIA audio function `10DE:10F8` at `01:00.1`; NVIDIA USB functions `10DE:1AD8` and `10DE:1AD9` at `01:00.2` and `01:00.3`. Evidence: earlier user-provided `WS75-PCI-Inventory.txt`; this is historical Windows enumeration, not a new macOS measurement.
- **Still unverified:** laptop panel/output wiring, macOS PCI visibility, live BAR layout and firmware/GSP initialization.

## Source audit

| Area | Evidence | Assessment |
| --- | --- | --- |
| PCI personality | `kexts/NVRM/Info.plist` matches vendor `10de` and PCI display base class `03`, including VGA `0300` and 3D controller `0302`. | No card-specific Info.plist change appears needed. |
| Installer IDs | `package/install.sh` includes `1EB6` in its supported-ID table; the installer also includes a Turing-and-newer fallback. | **Confirmed** historical hardware ID `10DE:1EB6`; matches the installer table. |
| NVIDIA support gate | `kexts/NVRM/NVRM.cpp` invokes `rm_is_supported_pci_device()` during probe and `rm_is_supported_device()` during initialization. | PCI matching alone does not establish successful RM/GSP initialization. |
| Turing startup | `kexts/NVRM/NVRM.cpp` has Turing-specific settle handling, including ranges `0x1E00–0x1FFF` and `0x2180–0x21FF`. | Relevant path exists; timing must be validated on target hardware. |
| Shader compiler | `plugin/NVMTLVendorCompiler.m` has chip-name-based SM target selection; `tools/test_card_support.py` exercises TU106 → SM 7.5. | Confirm whether the GPU reports TU104 or another chip identifier and that the fallback path works. |
| GPU family | `docs/CARD-SUPPORT.md` lists Quadro RTX among Turing devices. | Turing **physical validation is pending**. |
| Laptop display | `docs/CARD-SUPPORT.md` explicitly says a supported PCI ID does not implement an Optimus mux. | High risk: establish which GPU owns the internal panel and external ports. |
| OS/build | README documents macOS 26 support and a Tahoe-specific NVAccel build. | Source-level compatibility claim, not a tested WS75 build. |

## Required read-only hardware inventory

Run on **Windows PowerShell** (no driver installation):

```powershell
Get-PnpDevice -Class Display | Format-Table FriendlyName,Status,InstanceId -AutoSize
Get-CimInstance Win32_VideoController | Select-Object Name,PNPDeviceID,DriverVersion
```

On **macOS Terminal** (no driver installation):

```sh
system_profiler SPDisplaysDataType
ioreg -r -c IOPCIDevice -l | grep -E -i -B 12 -A 16 'NVDA|NVIDIA|<de100000>'
nvram boot-args
```

On **Ubuntu/Linux** (if available):

```sh
lspci -nnk -d 10de:
lspci -vv -d 10de:
```

For a more complete map, collect GPU PCI address, vendor/device/subsystem IDs, PCI class (0300 vs 0302), BAR sizes and addresses, and whether the internal LCD, HDMI, mini DisplayPort or USB-C outputs are physically wired to NVIDIA or Intel. Do not post serial numbers or unrelated identifiers.

## Safe acceptance criteria for Step 1

1. **Completed from prior Windows inventory:** GPU `10DE:1EB6`, subsystem `12B01462`, revision `A1`, PCI class `0300`, address `01:00.0`.
2. **Completed (table only):** `1EB6` appears in the installer device table; live NVIDIA support-gate execution remains untested.
3. Trace the Turing GSP/HAL and NVK shader-architecture selection paths for the reported chip.
4. Determine laptop display routing and whether a direct NVIDIA-connected output exists.
5. Run `python3 tools/test_card_support.py` on macOS with Xcode command-line tools; record results.
6. Document any gaps and a reversible test plan before changing boot args, SIP, AMFI, SecureBootModel, kexts or EFI.

## Security / recovery boundary

**Do not install or activate this experimental driver during Step 1.** The upstream README requests relaxed SIP/AMFI and disabled Apple Secure Boot. Those changes increase risk and must be separately reviewed with an EFI backup, a known-good boot path and an uninstall/recovery plan. Never modify the original working EFI as part of the audit.

## References

- [Driver README](../README.md)
- [Card support](CARD-SUPPORT.md)
- [NVRM PCI personality](../kexts/NVRM/Info.plist)
- [NVRM initialization](../kexts/NVRM/NVRM.cpp)
- [Installer device table](../package/install.sh)
- [CPU regression tests](../tools/test_card_support.py)
