# Security policy

MGU Assistant is experimental software that can modify an automotive infotainment head unit. Automated tests use simulated responses and do not establish vehicle safety or firmware compatibility. Review [compatibility](docs/compatibility.md) and the upstream projects before use.

## Reporting a vulnerability

Do not publish working secrets, vehicle identifiers or sensitive reproduction data in a public issue. If the repository's **Security → Report a vulnerability** option is available, use GitHub private vulnerability reporting. Otherwise open a minimal, non-sensitive issue requesting a private reporting channel; do not include the vulnerability's sensitive details until a suitable channel is established. There is no guaranteed response time or paid support service.

Include the affected version, the relevant component, a concise description of the impact and a reproduction using synthetic data where possible. State whether the problem concerns this assistant or an upstream component. Do not reproduce a vehicle-write issue on a live car merely to submit a report.

## Sensitive material

Do not upload private keys, enrollment material, coding backups, VINs, unredacted session logs or entire local state folders. Local state normally resides in `%LOCALAPPDATA%\MGUAssistant` and may contain vehicle identifiers, key paths, pinned server identities and write history. Review screenshots and error excerpts manually before sharing.

The bootstrap private key from the original upstream debug image is **shared**, not unique to a vehicle. Recovering that key locally does not provide unique per-car credentials. Unique per-car key provisioning is not implemented in this assistant. Limit access to the vehicle's network interfaces and protect local copies. Do not attempt improvised on-car key replacement as an incident response without understanding the upstream recovery constraints.

The first SSH fingerprint confirmation uses trust on first use over the selected connection. Verify the physical ENET connection and compare a fingerprint with an independent trusted reference when available. A changed stored fingerprint is blocked and must be investigated.

## Supply chain and release limitations

Resource downloads are pinned and checked with SHA-256. This detects a mismatch with the expected bytes, not whether those bytes are safe or compatible. Do not disable validation or edit a hash solely to accept an unexpected download.

Release executables are unsigned. Keep Windows security protections enabled. The assistant's source, upstream references and build scripts are available for review; their availability does not amount to an independent security audit.

Only the current public beta receives changes as maintenance capacity permits. Previous private versions are historical context, not supported recovery tools. No version promises protection against every interruption, preservation of all vehicle functions or an automatic rollback.

The privacy component's behavior does not establish complete anonymity or conceal modifications from service systems. The assistant is not endorsed by BMW or the upstream authors.
