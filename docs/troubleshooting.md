# Troubleshooting and recovery

If an operation fails, first determine **which stage actually completed**. A failed overall command does not mean the HU was left unchanged. Do not retry a flash, run `fix-key`, delete the journal or force a blocked operation to diagnose a later-stage problem.

Keep the car parked. Preserve the app's local state and private logs. After a completed or interrupted write, use a fresh read-only HU check before considering further action. If coding or original vehicle functions are not restored, stop changes and obtain appropriate coding assistance.

## Quick checks

| Symptom | Next check |
| --- | --- |
| PC check cannot find OpenSSH | Install/enable the Windows OpenSSH Client using Windows Optional Features, then repeat the PC check |
| No HU detected | Check ENET cable, adapter and selected interface; verify the vehicle is in the required powered state; an arbitrary `169.254.x.x` interface is not sufficient |
| Unsupported BTLD or uncertain architecture | Stop before writes; confirm HU_MGU/iDrive 7 and exact firmware against the project constraints |
| SSH port open but login fails | Select the correct private key, check the server identity and run authenticated root verification; do not reflash to test authentication |
| Flash button disabled after an attempt | Preserve the write journal; review the previous stage and fresh HU state. The block is intended to prevent accidental repeated writes |
| Missing Store resource / SHA-256 mismatch | Re-extract a verified release or run resource preparation from source; investigate a persistent mismatch without editing the expected hash |
| Store installs but has no online content | Check the HU's own supported hotspot/tethering setup; the PC's Internet connection is separate |
| Original functions missing after coding restore | Stop; verify the correct backup and seek coding assistance. Reflashing is not a coding repair |

## Case: flash completed, later enrollment check was busy

One owner-reported F44 installation completed **174/174 flash steps** with no reported response warnings. The coding identifier subsequently appeared as `FFFFFFFF`, consistent with coding having been cleared. The first `A0FD` activation returned success, but the later `22 17 2A` read-back received `7F 22 21` — UDS `busyRepeatRequest`.

That response came from a **read request**. It was not evidence that the certificate had been rejected, and it did not justify repeating the flash. The operation stopped before local key saving and persistence finished. The owner manually restored the original HU_MGU backup with BimmerCode and reported that the screen and menus worked again. A later fresh check found the original CAFD and an open SSH port.

The successful recovery in that case was:

1. Restore the correct original coding manually and verify original functions.
2. Read the current HU again; establish what had already completed.
3. Recover the original bootstrap private key **locally**, or select the existing correct key.
4. Confirm the server fingerprint and authenticate as root.
5. Complete only the missing SSH persistence step.
6. Install the Store using the verified local resources.
7. Request the separate final restart and check original functions and Store behavior.

This example is not a universal screen-recovery recipe. A black/frozen screen can have different causes. Do not interrupt an active write to try a coding restore; establish whether the operation has ended and which stage was reached first.

In the public beta, retry is bounded and limited to the matching busy response for that read-only enrollment check. Mutating requests and flash operations are not automatically repeated by this recovery mechanism.

## Understanding the key buttons

**Recupera chiave originale sul PC** copies the original upstream debug-image bootstrap key into local state. It does not contact the car to extract a newly generated key and does not change vehicle coding. That upstream key is shared; it is not unique per vehicle. It cannot recover an unrelated custom private key.

**Leggi impronta HU…** reads the SSH host identity. On first use, confirming it establishes a locally pinned identity over the connection you chose. Compare against an independent trusted reference if one exists. If the saved identity changes, investigate whether the HU or software changed, or whether the wrong endpoint is connected. Do not blindly delete `known_hosts` or accept any replacement.

**Verifica accesso root** checks authentication and UID `0`. A reachable port alone does not satisfy this step.

**Completa persistenza SSH…** is a write: it uses the pinned upstream persistence implementation to change HU services and disable debug. It is appropriate only after the required checks, with correct coding and working original functions. It does not reflash, repeat enrollment or restart automatically. If it fails, preserve the error and read the current state before any additional action.

## State, backups and write journals

The normal state folder is `%LOCALAPPDATA%\MGUAssistant`. It can contain vehicle identifiers, session details, local key information, pinned SSH identities and a per-vehicle write journal. Treat it as private.

The public beta records a flash attempt before starting the operation so a crash or partial result does not silently become permission for a second attempt. This guard covers recorded attempts on the same PC and state directory; it cannot discover attempts made with older versions, another PC or another state directory. Preserve this state across updates and moves. Do not switch or delete state to force a new attempt. Deleting it neither restores the HU nor proves it safe to repeat a write. There is no general “reset the error and flash again” recovery instruction.

The selected BimmerCode backup path is a reference, not evidence that the backup is correct. Use the [BimmerCode manual](https://bimmercode.app/manual/) and verify the correct original HU_MGU backup. Digital Key pairings are separate from coding and may need their own re-pairing procedure. Keep the physical vehicle key available.

## Previous private-build issues

| Version | Observed issue / change |
| --- | --- |
| `0.1.0` | Frozen Python output used CP1252 and failed on a Unicode arrow before the first flash frame was sent in the recorded case |
| `0.1.1` | Explicit UTF-8 subprocess output fixed that issue; the later busy read-back after a completed flash exposed an incomplete recovery path |
| `0.1.2` | Added local bootstrap-key recovery and a separate persistence action for an already accessible HU, with root/coding checks and strict server identity handling |
| `0.2.0-beta.1` | Public packaging, durable write journal and bounded retry for the specific read-only busy response; still no universal vehicle validation |
| `0.2.0-beta.2` | Reproducible source-build resource preparation using a hash-verified mirror of the original bundle after CI detected a changed upstream installer asset; original URLs and expected hashes preserved |

Do not infer “nothing was written” from an encoding error in an unrelated run: the exact recorded stage matters.

## Reporting a problem safely

Use the repository issue form for non-sensitive reports. Include the application version, Windows version, connection adapter, stage, sanitized error and the result of any fresh read already performed. Say explicitly whether a write had started or completed, and whether original functions currently work.

Remove VINs, personal paths/usernames, private/public keys, certificates, IP addresses that identify your own network, coding files and other personal information from attachments. Do not attach full state folders or raw backup files. For a security weakness or accidentally exposed private material, follow [SECURITY.md](../SECURITY.md).
