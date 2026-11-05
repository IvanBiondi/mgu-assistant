# MGU Assistant

A Windows 11 desktop guide for checking a BMW **MGU head unit running iDrive 7**, preparing SSH access and installing [MGU Store](https://github.com/robertnisipeanu/mgu-store) through ENET. The current interface is in Italian; [the complete Italian guide is here](README.it.md).

**Public beta: `v0.2.0-beta.2`. This is not a universal BMW installer.** Compatibility depends on the actual head unit and its firmware, not just the car model or the appearance of the menus. Read [compatibility](docs/compatibility.md) before connecting to a car. There is one owner-reported successful installation on an F44; other combinations are unverified.

This independent project is not BMW software and is not endorsed by BMW or the upstream projects. It does not promise a risk-free installation, warranty coverage or compatibility with every vehicle feature.

## Download and try it

1. Open [Releases](https://github.com/IvanBiondi/mgu-assistant/releases) and choose the Windows x64 ZIP for the desired version. Beta versions are marked **Pre-release**.
2. Compare the ZIP's SHA-256 with the release checksum. In PowerShell, run `Get-FileHash -Algorithm SHA256 .\<downloaded-file>.zip` with the actual filename.
3. Extract the **entire ZIP** to a local folder. Keep the application and its accompanying folders together; do not run it inside the ZIP.
4. Start `DEMO.cmd` to explore the workflow using simulated data. Demo mode does not operate the vehicle and blocks vehicle writes.
5. To perform vehicle writes, right-click `MGU-Assistant.exe` and choose **Run as administrator**, then follow the steps below. Demo mode and local PC checks do not require administrator privileges.

The portable release includes Python. The application is **unsigned**: a checksum confirms that your download matches the published bytes; it is not a publisher signature or a security certification. Do not disable Windows security protections to run it. You can inspect and build the source instead.

## What it does

- Checks the PC, ENET interface, gateway, head unit identifiers and SSH port before offering writes.
- Keeps preparation, root access, coding recovery, SSH persistence, Store installation and final restart as separate steps.
- Verifies downloaded resources against pinned SHA-256 values and installs the selected Store components from local files.
- Requires explicit confirmations for vehicle changes, records write attempts and prevents a simple repeat of an interrupted flash.
- Pins the SSH server fingerprint after a first-use confirmation and verifies authenticated root access.

Nothing is sent to a vehicle when the application starts. An open SSH port is **not** proof that root authentication works. Selecting a backup in the app is **not** a backup validation.

## Before sitting in the car

You need Windows 11 x64, Windows **OpenSSH Client**, a working ENET cable and Ethernet adapter, a physical vehicle key, and a suitable stabilized power supply for vehicle programming. Keep the PC powered and prevent sleep. Use only a vehicle you own or are authorized to modify, parked throughout the procedure.

Confirm independently that it has **HU_MGU and iDrive 7**. This application fixes the upstream root architecture to `id7`; it does not support NBT, NBT EVO, iDrive 6, iDrive 8 or iDrive 9. Its BTLD identifier gate, `00003F36`, is necessary for the offered workflow but does not establish firmware compatibility.

Create and export the appropriate **original HU_MGU coding backup** with BimmerCode before any change, using the [BimmerCode manual](https://bimmercode.app/manual/). Know how to restore it. This application neither creates that backup nor guarantees that it can restore every setting. Store a copy somewhere independent of the working PC.

**The root flash changes the HU software and can clear coding and Digital Key pairings. An interrupted or incompatible operation can leave the HU unusable.** A coding backup does not restore Digital Key pairings; have the physical key with you. Do not disconnect power or ENET, close the app or suspend the PC during a write.

## First installation, step by step

If SSH is already available, or a previous attempt reached the flash stage, start with [recovery](docs/troubleshooting.md). Do not repeat the first-install flash to solve a later problem.

1. **Connect and read.** Connect ENET and supply power. In **Connessione**, choose **Controlla PC e schede**, select the ENET adapter and choose **Leggi la HU**. Review the displayed vehicle, HU identifiers, versions and SSH status. Stop if these are unexpected or compatibility is unresolved.
2. **Confirm preparation.** In **Backup e sblocco**, select your exported backup file or folder. Confirm only statements you have actually checked: usable original backup, HU_MGU/iDrive 7 and firmware, stable power, and physical key. The app cannot check the contents of a BimmerCode backup.
3. **First-time root preparation, only if appropriate.** **Flash + Enable…** is a vehicle write. Use it only for a verified compatible unit without an existing completed or interrupted attempt. Read the confirmation, check the vehicle identifier and supply the requested VIN. Let the operation finish. If it fails, stop and inspect its recorded stage; a failed overall result can still mean the flash completed. Never clear the journal to retry.
4. **Restore and check coding.** After a completed flash, use BimmerCode manually to restore the correct original HU_MGU coding when required. This is outside the application. Confirm the screen, menus and original functions work, then perform a fresh **Leggi la HU**. If coding recovery fails, stop; do not flash again.
5. **Select the root key.** In **Chiave e coding**, use **Seleziona id_rsa…** for an existing private key. For the original upstream debug-image key, **Recupera chiave originale sul PC** makes a local copy; it does not extract a unique key from your car. See the key explanation below.
6. **Verify the server and root.** Choose **Leggi impronta HU…**. On the first direct ENET connection, verify that you are connected to the intended HU, compare the fingerprint with an independent reference if available, and confirm it. This is trust on first use, not independent authentication. Then choose **Verifica accesso root**; the authenticated account must have UID `0`. A changed stored fingerprint is a reason to investigate, not to delete the stored identity blindly.
7. **Complete SSH persistence if needed.** After coding is restored and original functions are checked, select the corresponding confirmation and use **Completa persistenza SSH…** if the first operation did not already complete it. This changes HU services and disables debug through the pinned upstream procedure. It does not repeat flashing or enrollment, and does not restart automatically.
8. **Install the Store.** In **Installa Store**, choose **Verifica file del pacchetto**. Review the Internet uplink option, then **Installa MGU Store…** and confirm. Installation uses the bundled local components and changes files and services on the HU. A hash mismatch must be investigated; do not replace the expected hash to make it pass.
9. **Restart separately and verify.** In **Riavvio e verifica**, choose **Riavvia la HU…** only after previous operations have completed. Wait for iDrive to return. Check the original menus, audio, cameras, parking functions and other fitted functions, then the Store and installed apps. Recheck after the next normal vehicle startup.

The offline installation does not give the car Internet access by itself. Configure a supported hotspot/tethering connection in the Store as described by its upstream project for online apps and updates. PC Internet access is separate from HU Internet access.

## Keys, privacy and local state

The original upstream bootstrap RSA private key is **shared**, not a secret generated uniquely for your vehicle. The app's recovery button copies that original key locally. Unique per-car provisioning is not implemented by this assistant. A root login key, an enrollment certificate key and a server fingerprint are different things.

Treat private keys, coding backups and session files as sensitive. Do not upload them to GitHub. Local state normally lives in `%LOCALAPPDATA%\MGUAssistant`; it can include vehicle identifiers, key paths, pinned host identities and the write journal. Keep it private and preserve it when moving or updating the app. Deleting state does not undo changes to the car.

The write journal protects attempts recorded on the same PC and state directory. It cannot discover attempts made with older versions, another PC or another state directory. Do not delete or switch state to force a new attempt; establish the actual HU state first.

The bundled privacy component changes certain reporting behavior according to its upstream implementation. It is not a promise of invisibility, complete privacy or protection against service/warranty consequences.

## Source, verification and development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/prepare_resources.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --demo
.\.venv\Scripts\python.exe scripts/build.py
.\.venv\Scripts\python.exe scripts/package.py
```

Use Python 3.12 on Windows with Tkinter available. Resource preparation requires Internet access. The Git repository contains the assistant's source, documentation and pinned resource metadata, **not** upstream executables, private keys, vehicle logs or backups. `scripts/prepare_resources.py` prepares the pinned resources in ignored directories and refuses SHA-256 mismatches. `scripts/build.py` creates the application bundle; `scripts/package.py` creates the ZIP and checksum in `release/`.

An upstream installer asset changed after the original download; CI detected the SHA-256 mismatch. To keep source builds reproducible, the verified original resource bundle is mirrored in this repository's [resources-20261105 release](https://github.com/IvanBiondi/mgu-assistant/releases/tag/resources-20261105). When the local resource cache is missing, preparation uses that hash-verified archive. The original official source URLs and expected SHA-256 values remain recorded; this mirror does not replace attribution or upstream licenses. Verification remains mandatory: the expected hashes were not relaxed to accept the changed installer.

CI and local automated tests exercise code and simulated vehicle responses. They do not test a real car, establish electrical safety or prove firmware compatibility. The release notes distinguish automated checks from the owner's installation report.

## Upstream projects and licenses

- [idrive7-8-ssh-root](https://github.com/cauliflowermossgrape/idrive7-8-ssh-root): root/enrollment/persistence implementation; its own license and compatibility constraints apply. The assistant exposes the `id7` path only.
- [MGU Store](https://github.com/robertnisipeanu/mgu-store): Store and component installation; GPL-3.0-or-later, with component-specific notices where applicable.

The assistant's original code is [MIT licensed](LICENSE). Upstream components keep their own licenses; the MIT license does not relicense those components. Release packages must retain the included notices and source references.

For errors, start with [troubleshooting](docs/troubleshooting.md). For compatibility reports and patches, read [CONTRIBUTING.md](CONTRIBUTING.md). For sensitive security reports, read [SECURITY.md](SECURITY.md).
