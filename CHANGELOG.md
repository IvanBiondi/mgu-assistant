# Changelog

## Unreleased

- Include the Simplified Chinese UI and companion README merged in #2; document locale detection, `MGU_UI_LANGUAGE` and English diagnostic fallback. The beta.3 ZIP predates these changes.
- Support direct ENET discovery on link-local and RFC1918 private IPv4 subnets (#3). Read the current Windows prefix, bind discovery and diagnostics to the selected address, and reject off-subnet peers, network/broadcast endpoints and ambiguous gateways.
- Include `i18n.py` and `README.zh-CN.md` in portable source packages, and the Chinese guide beside the executable.
- Record the X3M F97 hardware/firmware report from #1 as read-only detection, with installation and original-function compatibility explicitly unverified.
- Preserve firmware gates, confirmation steps, SSH identity checks, flash journals and pinned upstream resources. No new real-vehicle validation is claimed.

## 0.2.0-beta.3

- Translate the five-stage Windows interface, confirmations, errors, activity messages, file dialogs and command-line help into English.
- Translate the bundled offline guide and align the English README and recovery documentation with the actual English button labels.
- Add real demo screenshots of all five screens, with synthetic data and vehicle writes disabled.
- Update the optional Italian companion guide to refer to the English interface.
- Preserve vehicle operations, compatibility gates, confirmations, flash journals, SSH checks and pinned upstream components. No additional BMW model or firmware compatibility is claimed.

## 0.2.0-beta.2

- Preserve the verified upstream originals in a content-addressed resource snapshot. The upstream installer asset changed after the initial download; the first clean GitHub build correctly refused it.
- Prepare resources from the pinned snapshot when a local cache is absent, verifying both the archive and every original file. Official source URLs and original hashes remain recorded.
- Add regression checks for corrupted and unsafe resource archives. Vehicle behavior and component versions are unchanged from beta.1.

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
