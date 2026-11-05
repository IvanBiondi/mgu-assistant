"""Build the Windows x64 portable app. No vehicle is contacted."""
from pathlib import Path
import marshal
import os
import platform
import struct
import subprocess
import sys
import tempfile
import types
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def verify_frozen_filenames(distribution):
    """Inspect, without executing, frozen code for leaked absolute build paths."""
    from PyInstaller.archive.readers import CArchiveReader
    checked = 0

    def inspect_code(code):
        nonlocal checked
        if not isinstance(code, types.CodeType):
            return
        filename = Path(code.co_filename)
        if filename.is_absolute() or filename.drive:
            raise RuntimeError("Frozen bytecode still contains an absolute build path.")
        checked += 1
        for constant in code.co_consts:
            if isinstance(constant, types.CodeType):
                inspect_code(constant)

    archive = CArchiveReader(str(distribution / "MGU-Assistant.exe"))
    for name, entry in archive.toc.items():
        if entry[-1] in {"s", "m", "M"}:
            inspect_code(marshal.loads(archive.extract(name)))
        elif entry[-1] == "z":
            embedded = archive.open_embedded_archive(name)
            for module in embedded.toc:
                inspect_code(embedded.extract(module))
    with zipfile.ZipFile(distribution / "_internal/base_library.zip") as library:
        for name in library.namelist():
            if name.endswith(".pyc"):
                inspect_code(marshal.loads(library.read(name)[16:]))
    for filename in (distribution / "_internal").rglob("*.pyc"):
        inspect_code(marshal.loads(filename.read_bytes()[16:]))
    if not checked:
        raise RuntimeError("No frozen code objects were inspected.")
    print(f"Verified {checked} frozen code objects: no absolute co_filename paths.")
    return checked


def main():
    if sys.platform != "win32" or struct.calcsize("P") != 8 or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Build requires Windows x64 and a 64-bit x64 Python installation.")
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Build requires Python 3.12 with Tkinter.")
    import tkinter  # noqa: F401: fail early when the Python installation lacks Tk.
    import PyInstaller
    if PyInstaller.__version__ != "6.22.3":
        raise SystemExit("Install the versions in requirements-dev.txt before building.")
    if not (ROOT / "resources/integrity.json").is_file():
        raise SystemExit("Run python scripts/prepare_resources.py first.")
    with tempfile.TemporaryDirectory(prefix="mgu-build-check-") as temporary:
        subprocess.run([sys.executable, str(ROOT / "main.py"), "--self-test",
                        "--resource-dir", str(ROOT / "resources"),
                        "--state-dir", str(Path(temporary) / "state")], cwd=ROOT, check=True)
    os.environ.setdefault("PYINSTALLER_CONFIG_DIR", str(ROOT / "build-cache"))
    import PyInstaller.__main__
    PyInstaller.__main__.run([
        str(ROOT / "main.py"), "--name", "MGU-Assistant", "--onedir",
        "--console", "--hide-console", "hide-early", "--noupx", "--noconfirm", "--clean",
        "--icon", str(ROOT / "assets/app.ico"),
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"), "--paths", str(ROOT / "resources/vendor/root"),
        "--hidden-import", "ssh_enable", "--collect-submodules", "mgu7",
        "--collect-all", "cryptography", "--hidden-import", "ctypes.wintypes",
        "--hidden-import", "tkinter", "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.filedialog", "--hidden-import", "tkinter.messagebox",
        "--hidden-import", "tkinter.simpledialog", "--hidden-import", "tkinter.scrolledtext",
        "--exclude-module", "torch", "--exclude-module", "numpy", "--exclude-module", "pandas",
        "--exclude-module", "matplotlib", "--exclude-module", "scipy", "--exclude-module", "IPython",
        "--exclude-module", "PIL", "--exclude-module", "cv2",
    ])
    verify_frozen_filenames(ROOT / "dist/MGU-Assistant")
    print("Executable ready in dist/MGU-Assistant. Run scripts/package.py for the offline ZIP.")


if __name__ == "__main__":
    main()
