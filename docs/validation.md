# Validation of v0.2.0-beta.2

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
