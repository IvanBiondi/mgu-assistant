"""Package only reviewed source paths and hash-verified resources, without vehicle I/O."""
from pathlib import Path
import ast
import hashlib
import importlib.metadata
import json
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "main.py", "backend.py", "LICENSE", "README.md", "README.it.md",
    "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md",
    "requirements.txt", "requirements-dev.txt", "upstream-lock.json",
    ".gitignore", ".gitattributes", "assets/app.ico", "resources/guida.html",
)
SOURCE_DIRS = {"scripts": {".py"}, "tests": {".py"}, "docs": {".md", ".html", ".png"},
               ".github": {".yml", ".yaml", ".md"}}


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_path(base, relative):
    path = (base / relative).resolve()
    if path == base.resolve() or not path.is_relative_to(base.resolve()):
        raise ValueError(f"Path leaves package directory: {relative}")
    return path


def copy(source, destination):
    if source.is_symlink():
        raise ValueError(f"Refusing a symlink: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def version():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(n, ast.Name) and n.id == "VERSION" for n in node.targets):
            result = ast.literal_eval(node.value)
            if isinstance(result, str) and result and all(c.isalnum() or c in ".-" for c in result):
                return result
    raise ValueError("Cannot read a safe VERSION from main.py")


def main():
    distribution = ROOT / "dist/MGU-Assistant"
    if not (distribution / "MGU-Assistant.exe").is_file():
        raise SystemExit("Run python scripts/build.py first.")
    resources = ROOT / "resources"
    manifest = json.loads((resources / "integrity.json").read_text(encoding="utf-8"))
    for relative, digest in manifest.items():
        if sha256(safe_path(resources, relative)) != digest:
            raise SystemExit(f"Resource changed: {relative}. Prepare resources again before packaging.")
    for required in ("README.md", "LICENSE", "upstream-lock.json", "THIRD_PARTY_NOTICES.md"):
        if not (ROOT / required).is_file():
            raise SystemExit(f"Missing required public file: {required}")
    output = ROOT / "release"
    output.mkdir(exist_ok=True)
    name = "MGU-Assistant-Windows-x64-v" + version()
    archive = output / (name + ".zip")
    with tempfile.TemporaryDirectory(prefix="package-", dir=output) as temporary:
        destination = Path(temporary) / name
        destination.mkdir()
        # PyInstaller outputs are the executable and its private _internal runtime only.
        copy(distribution / "MGU-Assistant.exe", destination / "MGU-Assistant.exe")
        for source in sorted((distribution / "_internal").rglob("*")):
            if source.is_file():
                copy(source, destination / "_internal" / source.relative_to(distribution / "_internal"))
        for relative in manifest:
            copy(safe_path(resources, relative), safe_path(destination / "resources", relative))
        copy(resources / "integrity.json", destination / "resources/integrity.json")
        for relative in SOURCE_FILES:
            source = ROOT / relative
            if source.is_file():
                copy(source, destination / "source" / relative)
        for directory, suffixes in SOURCE_DIRS.items():
            for source in sorted((ROOT / directory).rglob("*")):
                if source.is_file() and source.suffix in suffixes and "__pycache__" not in source.parts:
                    copy(source, destination / "source" / source.relative_to(ROOT))
        for relative in ("README.md", "README.it.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"):
            if (ROOT / relative).is_file():
                copy(ROOT / relative, destination / relative)
        for source in sorted((ROOT / "docs").rglob("*")):
            if source.is_file() and source.suffix in SOURCE_DIRS["docs"]:
                copy(source, destination / "docs" / source.relative_to(ROOT / "docs"))
        python_license = Path(sys.base_prefix) / "LICENSE.txt"
        if not python_license.is_file():
            raise SystemExit("Python LICENSE.txt is missing from this Python installation.")
        copy(python_license, destination / "resources/licenses/Python-LICENSE.txt")
        dependency_versions = {}
        for dependency_name in ("cryptography", "PyInstaller"):
            distribution_metadata = importlib.metadata.distribution(dependency_name)
            dependency_versions[dependency_name] = distribution_metadata.version
            license_files = [p for p in distribution_metadata.files or ()
                             if p.name.upper().startswith(("LICENSE", "COPYING"))]
            if not license_files:
                raise SystemExit(f"No license files found for {dependency_name}; packaging stopped.")
            for relative in license_files:
                copy(Path(distribution_metadata.locate_file(relative)),
                     destination / "resources/licenses" / dependency_name / relative.name)
        (destination / "BUILD-INFO.json").write_text(json.dumps({
            "app_version": version(), "python": ".".join(map(str, sys.version_info[:3])),
            "dependencies": dependency_versions, "platform": "Windows x64", "signed": False,
            "note": "Pinned inputs and stable archive timestamps; byte-identical rebuilds are not guaranteed."
        }, indent=2) + "\n", encoding="utf-8")
        (destination / "DEMO.cmd").write_bytes(b'@echo off\r\nstart "" "%~dp0MGU-Assistant.exe" --demo\r\n')
        (destination / "source/PORTABLE-SOURCE.txt").write_text(
            "This directory contains the MGU Assistant source and build instructions.\n"
            "To run from here: python main.py --demo --resource-dir ../resources\n"
            "To rebuild independently: follow README.md and run scripts/prepare_resources.py.\n"
            "Exact upstream source archives and licenses are in ../resources/sources and ../resources/licenses.\n",
            encoding="utf-8")
        hashes = {p.relative_to(destination).as_posix(): sha256(p)
                  for p in sorted(destination.rglob("*")) if p.is_file()}
        (destination / "PACKAGE-SHA256.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=5) as bundle:
            for source in sorted(destination.rglob("*")):
                if source.is_file():
                    # Stable timestamps avoid differences caused only by download/copy times.
                    entry = zipfile.ZipInfo(name + "/" + source.relative_to(destination).as_posix(), (2020, 1, 1, 0, 0, 0))
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    entry.external_attr = 0o100644 << 16
                    bundle.writestr(entry, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=5)
    digest = sha256(archive)
    archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n", encoding="ascii")
    print(json.dumps({"archive": str(archive), "sha256": digest, "bytes": archive.stat().st_size,
                      "files": len(hashes), "signed": False}, indent=2))


if __name__ == "__main__":
    main()
