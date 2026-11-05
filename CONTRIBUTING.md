# Contributing

Thanks for helping make MGU Assistant easier to understand and safer to operate. The public release is a beta for MGU iDrive 7, with one owner-reported completed installation and automated tests that use simulated responses. Please keep that evidence boundary explicit.

## Before opening an issue

Read [compatibility](docs/compatibility.md) and [troubleshooting](docs/troubleshooting.md). Use the issue form for reproducible non-sensitive bugs. Do not repeat a vehicle write just to collect evidence.

Useful information includes:

- Assistant version and whether it was a release bundle or source build.
- Windows version, Ethernet adapter and connection arrangement.
- Optional vehicle model/year and exact HU BTLD/HWEL/CAFD identifiers and versions, with all VINs removed.
- The action selected, observed result and expected result.
- Whether a write began or completed, current original-function status, and the result of a fresh read already performed.
- A short, manually sanitized error excerpt.

Never attach keys, certificates, coding backups, unredacted logs or entire state folders. Review screenshots for vehicle identifiers and personal paths. Use [SECURITY.md](SECURITY.md) for sensitive reports.

## Development setup

Use Windows, Python 3.12 with Tkinter and an isolated virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/prepare_resources.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --demo
```

Resource preparation needs Internet access and validates pinned SHA-256 values. Never put downloaded upstream binaries, private keys, real vehicle identifiers, local state or backups into Git. A hash failure needs investigation; changing the expected value is not a troubleshooting shortcut.

Use `scripts/build.py` to build the application and `scripts/package.py` to create the release ZIP and checksum. Build/test commands run on the PC; the normal test suite must not require or contact a car.

## Pull requests

Describe the concrete problem, the resulting behavior and how you verified it. Distinguish automated checks from any owner-reported vehicle result. Include focused tests for changes to parsing, process output, key validation, SSH identity checks, write eligibility, durable journals or retry behavior. Simulate hardware/network responses and failure paths.

Keep these properties intact:

- No vehicle operation on application startup; demo mode blocks vehicle writes.
- Separate user actions for root flash, persistence, Store installation and final restart.
- Fresh identity checks and explicit confirmation before writes.
- The `id7` boundary and BTLD gate do not become claims of universal firmware support.
- Host-key changes are investigated rather than silently accepted.
- Write attempts remain recorded through interruption or failure.
- Busy retries stay bounded and limited to the specific read-only request; do not add retries around mutating commands.
- No force-flash button, automatic reflash, journal-clearing bypass or implied automatic rollback.

For upstream changes, identify the source commit/release, review behavior and licenses, update the pinned metadata through a deliberate review and document the verification performed. Keep the upstream license and source references in distributed bundles. Do not present a checksum as a security audit.

Compatibility reports are welcome without new writes. Describe exactly which stages were observed: read-only discovery, root authentication, persistence, Store installation and original-function checks after restart are different levels of evidence. Do not label a vehicle family supported based on a single matching identifier.
