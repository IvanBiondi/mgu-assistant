# Compatibility and evidence

MGU Assistant `v0.2.0-beta.3` targets Windows 11 x64 and **BMW HU_MGU with iDrive 7** over ENET. It is an experimental public beta, not a certification for all BMWs or all iDrive 7 releases.

## Platform boundary

| Configuration | Status in this assistant |
| --- | --- |
| HU_MGU, independently confirmed iDrive 7, BTLD `00003F36` | Candidate only; exact hardware/software compatibility still needs verification |
| BTLD identifier other than `00003F36` | Not supported by the exposed flash workflow |
| NBT, NBT EVO, iDrive 6 | Unsupported |
| iDrive 8 / iDrive 9 | Unsupported, including where the upstream root project has additional capabilities |
| Retrofit or replaced HU | Judge the installed HU and software; the vehicle badge/year is insufficient |
| Windows 11 x64 | Release target |
| Other operating systems / CPU architectures | No supported packaged release |

The root architecture is fixed to upstream `id7`. The interface requires the user to confirm HU_MGU and iDrive 7 because the BTLD identifier alone is not a reliable architecture/version proof. A passed identifier check, accessible SSH port or valid SHA-256 is not a compatibility guarantee.

## Available real-vehicle evidence

| Item | Owner-reported configuration |
| --- | --- |
| Vehicle | BMW F44 |
| System | MGU, iDrive 7 |
| BTLD | `00003F36`, version `030.016.006` |
| CAFD | `00003E52`, version `008.010.124` |
| PC / connection | Windows 11 x64 / ENET |
| Outcome | Owner reported working original screen/menus after BimmerCode coding restore, working Store and additional apps |

This was one installation using earlier private builds, with a recovered interruption after flashing. It is **not** a physical-vehicle validation of every path in the public beta. It does not establish long-term reliability, compatibility with every factory option or success on another HU with the same model name. No VIN or private session files are published.

## Read-only report: 2021 BMW X3M F97

[Issue #1](https://github.com/IvanBiondi/mgu-assistant/issues/1) reports successful read-only identification with beta.3:

| Identifier | Reported value | Version |
| --- | --- | --- |
| HWEL | `0000786C` | `001.003.001` |
| BTLD | `00003F36` | `016.020.036` |
| SWFL | `00005CC5` | `016.020.004` |
| CAFD | `00003E52` | `006.036.030` |

The MGU filter passed and SSH was unreachable. **This exact combination has no successful installation or original-function verification recorded in this repository.** The filter recognizes the BTLD identifier; it does not certify this firmware. An unreachable SSH port does not establish whether SSH is disabled, filtered or otherwise unreachable, and is not a reason to flash.

There is no verified result here for the display, touchscreen, parking cameras or M-specific functions on this F97 configuration. An existing BimmerCode backup is useful preparation, but neither proves compatibility nor guarantees complete recovery of every setting or Digital Key pairing. Keep this configuration marked **read-only detected / installation unverified** until independent evidence is available. Do not perform a write solely to confirm compatibility.

## What is tested automatically

Automated tests and demo checks cover software behavior such as parsing, validation, resource integrity handling, subprocess text encoding, simulated recovery, write guards and bounded read-only retry behavior. They use local files and simulated responses. CI does not have a connected car.

No automated test here can prove suitable vehicle power, a usable coding backup, firmware compatibility, recovery after power loss, preservation of all vehicle features or dealer/service behavior after modification.

## Upstream scope and pinned resources

The authoritative source projects are [idrive7-8-ssh-root](https://github.com/cauliflowermossgrape/idrive7-8-ssh-root) and [MGU Store](https://github.com/robertnisipeanu/mgu-store). Consult their constraints as well as this assistant's narrower scope. An upstream feature does not imply that it is exposed or supported in the assistant.

The resource preparation script uses pinned sources and SHA-256 values. The initial offline Store bundle targets:

| Component | Version |
| --- | --- |
| Store | `0.9.21` |
| Deploy | `0.7.17` |
| Updater | `0.8.25` |
| Renderer | `0.6.11` |
| HU Python | `1.0.2` |
| App privacy | `1.7.1` |
| Internet uplink | `0.7.3` |

These versions describe packaged resources, not a claim that each component has been audited or tested on every firmware. Store-driven updates after installation are separate from this pinned initial bundle.

## Reporting another configuration

See [CONTRIBUTING.md](../CONTRIBUTING.md). Report exact BTLD/HWEL/CAFD identifiers and versions where available, app version, Windows version, connection hardware and observed result. Distinguish a read-only detection result from successful root access, persistence, Store installation and post-restart original-function checks. Never publish VINs, keys, coding backups or unredacted session logs.

Do not perform a new write solely to fill in the table. Reports of an existing installation or read-only observations are useful without additional risk.
