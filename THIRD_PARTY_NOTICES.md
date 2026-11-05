# Third-party components and provenance

MGU Assistant is an independent integration, not a BMW product or an official release of the projects below. The interface and integration code use the MIT license in `LICENSE`. Upstream components keep their own licenses.

| Component | Pinned source | License |
| --- | --- | --- |
| idrive7-8-ssh-root | [a4aa8932f1a61e784b761ea04ecc64f82c87a0d3](https://github.com/cauliflowermossgrape/idrive7-8-ssh-root/tree/a4aa8932f1a61e784b761ea04ecc64f82c87a0d3) | Unlicense |
| mgu-store reference snapshot | [648c7874b40c51375e6647f936f85ae501498bd1](https://github.com/robertnisipeanu/mgu-store/tree/648c7874b40c51375e6647f936f85ae501498bd1) | GPL-3.0-or-later |
| mgu-store installer source | [2eb7c4f1b886eeec998bf68e2be886db51ecdfd4](https://github.com/robertnisipeanu/mgu-store/tree/2eb7c4f1b886eeec998bf68e2be886db51ecdfd4) | GPL-3.0-or-later |
| mgu-store catalog/build source | [2cf83fc22f25876b57a775eee8ce64ebe4d4fa60](https://github.com/robertnisipeanu/mgu-store/tree/2cf83fc22f25876b57a775eee8ce64ebe4d4fa60) | GPL-3.0-or-later |

The downloadable bundle retains original source archives under `resources/sources`, upstream license texts and README files under `resources/licenses`, and the root source under `resources/vendor/root`. The installer and seven payloads are unmodified upstream release artifacts. `upstream-lock.json` records their URLs, byte counts and SHA-256 values. Mutable release tags are accepted only when the files still match those pinned hashes.

The offline catalog is derived from the pinned original catalog: only the seven bundled components remain and artifact URLs become local filenames. Its source archive and original catalog are included. Local SHA-256 manifests detect corruption or changes against the bundled manifest; they are not independent publisher signatures.

The [resource snapshot](https://github.com/IvanBiondi/mgu-assistant/releases/tag/resources-20261105) mirrors these same verified originals because upstream release assets can be replaced. Archive members are named by SHA-256 and mapped to original names and URLs in the attached lock file. Resource preparation verifies the archive and each member before using it; the mirror does not replace the original attribution or license.

The root source is not edited. Integration hooks in `backend.py` bind the selected ENET interface, isolate persistence, enforce the local attempt journal, verify key-file permissions and debug-off state, and retry only the specific Busy response on a certificate-address read. Review those hooks together with the original source when auditing the behavior.

Python, Tcl/Tk, cryptography, OpenSSL, PyInstaller and installer/payload dependencies retain their respective licenses and notices. See the notices included in the distributed runtime and original source archives. The MIT license above does not relicense them. The root project's original bootstrap key is public upstream material, shared between installations using that mode; it is not a personal credential generated for the owner of this repository.

BMW, iDrive and BimmerCode names identify products and compatibility context only. No affiliation or endorsement is implied.
