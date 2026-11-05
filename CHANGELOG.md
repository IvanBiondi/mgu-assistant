# Changelog

## 0.2.0-beta.1

First public Windows x64 beta for candidate BMW MGU iDrive 7 head units.

- Generalized vehicle branding and documented compatibility limits.
- Added a persistent per-vehicle flash-attempt journal: restarting the app cannot authorize a second attempt.
- Invalidated UI authorization after failed writes and after a successful initial flash.
- Added bounded retries for the enrollment certificate-address read only, when the ECU returns Busy (NRC 0x21). No writes are retried.
- Require an explicitly verified debug-off state before reporting persistence success; prefer Windows' system OpenSSH and verify permissions on key copies created by the app.
- Keep worker progress processing alive if the log disk becomes unwritable and block subsequent writes until logging is restored.
- Preserved the separate recovery path: export the upstream bootstrap key locally, verify root, and complete persistence without another flash or enrollment.
- Preserved explicit ENET adapter binding, vehicle identity checks, strict SSH host-key checking after initial acceptance, offline payload hashes, demo isolation and UTF-8 worker output.
- Added pinned upstream preparation, reproducible build instructions, automated regression checks, English and Italian guides, and privacy-conscious issue reporting.

Validation is local and simulated. An owner reported a working Store and additional apps on one F44 using the preceding private version. This release has not been independently validated across BMW models or firmware versions.
