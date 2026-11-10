# Validation records

## v0.2.0-beta.3 — English interface

Checks completed on Windows 11 x64 with Python 3.12.10 on 2026-11-10:

- All 56 automated regression tests passed with simulated vehicle I/O.
- The syntax trees of `main.py` and `backend.py` were compared with beta.2: only string values changed. Vehicle commands, control flow, compatibility checks and resource pins were preserved.
- All 18 upstream originals and 58 prepared resource files passed their existing integrity checks; the seven offline Store components retain the same versions.
- Source and frozen executable self-tests passed, including UTF-8 output with a parent environment requesting CP1252.
- All five demo screens opened and closed in both source and frozen builds. The English source interface was also reviewed visually; the screenshots in `docs/images` contain only the built-in synthetic demo data, with vehicle writes disabled.
- The build inspected 10,760 frozen code objects and found no absolute source filenames.

These checks did not contact or modify a vehicle. This translation release adds no evidence of compatibility with additional BMW models or firmware. Windows-owned dialog controls and external tool messages can follow their own language settings.

GitHub Actions repeats the regression tests and checks the release executable before attaching the Windows ZIP and checksum. Check the visible workflow result for the hosted build; the local result alone does not establish that the hosted build succeeded.

## v0.2.0-beta.2

Local checks completed on Windows x64 on 2026-11-05:

- 56 automated regression tests passed. They cover demo isolation, VIN/interface changes, SSH host-key changes, payload tampering, flash journal persistence and concurrent attempts, bounded read-only Busy retries, explicit debug-off verification, key permissions, UTF-8 worker output and invalidation of UI state after failed writes.
- Resource-bundle regression tests reject corrupted archives, unexpected members, traversal, symlinks, aliases, duplicate entries and byte/hash mismatches. The mirror preserves the original artifact hashes.
- The upstream persistence orchestration was exercised with all vehicle I/O simulated; flash and enrollment calls were forbidden in that test.
- 18 original upstream downloads matched their pinned sizes and SHA-256 values. The assembled resources contain 58 manifest entries and seven offline Store components.
- Both source and frozen executable self-tests passed. The frozen executable passed with its parent environment requesting cp1252, reproducing the conditions behind the earlier progress-log encoding failure.
- All five demo screens opened and closed successfully in the source and packaged executable smoke checks.
- 14,244 frozen Python code objects were checked for absolute source filenames; none were present. The public source allowlist was checked for the original owner's identifiers, local paths and private-key contents.
- Windows key-file permissions were applied and read back on a temporary synthetic file. No imported user key was changed.

These are local and simulated checks, not a vehicle certification. No vehicle connection or flash was performed while preparing this public version. A prior private version has one owner-reported F44 success; that report does not validate every path or other models and firmware. See [compatibility](compatibility.md).

GitHub Actions repeats the checks in a clean Windows environment and builds release assets from the published tag. Its visible run result is the authority for the hosted build; a local passing result does not imply the hosted run has passed.
