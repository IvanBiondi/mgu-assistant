"""Fetch pinned public upstream files and assemble offline resources. No vehicle I/O.

The lock records expected bytes and SHA-256 for every downloaded original. A hash
is an integrity pin, not an author signature. Downloads never update the lock.
"""
from pathlib import Path, PurePosixPath
import argparse
import copy
import hashlib
import json
import re
import shutil
import stat
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
KINDS = {"file", "root_source", "store_source", "installer_source", "catalog_source", "catalog", "payload"}
OFFICIAL_HOSTS = {"github.com", "codeload.github.com", "raw.githubusercontent.com", "objects.githubusercontent.com",
                  "release-assets.githubusercontent.com", "github-releases.githubusercontent.com"}


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative_path(value):
    """Reject traversal and Windows path aliases before joining a relative path."""
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise ValueError(f"Unsafe relative path: {value!r}")
    parts = value.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    for part in parts:
        if part in {"", ".", ".."} or part.endswith((".", " ")) or re.search(r'[\x00-\x1f:*?"<>|]', part):
            raise ValueError(f"Unsafe relative path: {value!r}")
        if part.split(".", 1)[0].upper() in reserved:
            raise ValueError(f"Windows device path is not a resource: {value!r}")
    return PurePosixPath(value)


def below(base, relative):
    path = base.joinpath(*relative_path(relative).parts)
    if not path.resolve().is_relative_to(base.resolve()):
        raise ValueError(f"Path leaves resource directory: {relative}")
    return path


def validate_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Only HTTPS URLs on the pinned official GitHub hosts are allowed.")


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        validate_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


def load_lock(path):
    lock = json.loads(path.read_text(encoding="utf-8-sig"))
    if lock.get("schema") != 1 or not isinstance(lock.get("artifacts"), list):
        raise ValueError("Unsupported upstream-lock.json schema.")
    names = set()
    for artifact in lock["artifacts"]:
        relative_path(artifact["target"])
        if artifact["target"].casefold() in names:
            raise ValueError("Duplicate lock target: " + artifact["target"])
        names.add(artifact["target"].casefold())
        if artifact["target"].split("/")[0] not in {"sources", "licenses", "installer", "payload"}:
            raise ValueError("Unexpected lock target directory: " + artifact["target"])
        if artifact["kind"] not in KINDS or not re.fullmatch(r"[a-f0-9]{64}", artifact["sha256"]):
            raise ValueError("Invalid kind or SHA-256 in lock: " + artifact["target"])
        if type(artifact["bytes"]) is not int or artifact["bytes"] <= 0:
            raise ValueError("Invalid byte size in lock: " + artifact["target"])
        validate_url(artifact["url"])
    for kind in ("root_source", "catalog", "store_source", "installer_source", "catalog_source"):
        if sum(a["kind"] == kind for a in lock["artifacts"]) != 1:
            raise ValueError("Lock must contain exactly one " + kind)
    return lock


def matches(path, artifact):
    return path.is_file() and not path.is_symlink() and path.stat().st_size == artifact["bytes"] and sha256(path) == artifact["sha256"]


def fetch(artifact, cache, offline):
    # Cache can be content-addressed or a previously prepared resource directory.
    candidates = [cache / artifact["sha256"], below(cache, artifact["target"]), cache / PurePosixPath(artifact["target"]).name]
    for candidate in candidates:
        if matches(candidate, artifact):
            print("Verified cache: " + artifact["target"], flush=True)
            return candidate
    if offline:
        raise ValueError("Pinned original is absent or changed in cache: " + artifact["target"])
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / artifact["sha256"]
    print("Downloading and verifying: " + artifact["target"], flush=True)
    request = urllib.request.Request(artifact["url"], headers={"User-Agent": "MGU-Assistant-resource-builder/0.2", "Accept-Encoding": "identity"})
    opener = urllib.request.build_opener(OfficialRedirects())
    with tempfile.NamedTemporaryFile(prefix="download-", dir=cache, delete=False) as temporary:
        partial = Path(temporary.name)
        try:
            with opener.open(request, timeout=60) as response:
                validate_url(response.url)
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > artifact["bytes"]:
                        raise ValueError("Download exceeds pinned size: " + artifact["target"])
                    temporary.write(block)
        except BaseException:
            temporary.close()
            partial.unlink(missing_ok=True)
            raise
    try:
        if not matches(partial, artifact):
            raise ValueError("SHA-256 or byte count differs from lock: " + artifact["target"] + ". No resource was installed.")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def extract_root(archive, destination):
    """Strip the single GitHub source root; reject links, collisions and traversal."""
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        roots = set()
        checked = []
        seen = set()
        if sum(info.file_size for info in entries) > 200 * 1024 * 1024:
            raise ValueError("Unexpectedly large root source archive.")
        for info in entries:
            relative = relative_path(info.filename.rstrip("/"))
            roots.add(relative.parts[0])
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFDIR, stat.S_IFREG)):
                raise ValueError("Links or special files are forbidden in source archives.")
            if len(relative.parts) == 1:
                if not info.is_dir():
                    raise ValueError("Expected a single directory at archive root.")
                continue
            stripped = PurePosixPath(*relative.parts[1:]).as_posix()
            if stripped.casefold() in seen:
                raise ValueError("Duplicate source archive path: " + stripped)
            seen.add(stripped.casefold())
            if info.is_dir() or "__pycache__" in relative.parts or ".git" in relative.parts or relative.suffix in {".pyc", ".pyo"}:
                continue
            checked.append((info, stripped))
        if len(roots) != 1:
            raise ValueError("Expected exactly one GitHub source directory.")
        for info, relative in checked:
            path = below(destination, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, path.open("wb") as output:
                shutil.copyfileobj(source, output)


def make_catalog(lock, staging):
    original = next(a for a in lock["artifacts"] if a["kind"] == "catalog")
    catalog = json.loads(below(staging, original["target"]).read_text(encoding="utf-8-sig"))
    payloads = {PurePosixPath(a["target"]).name: a for a in lock["artifacts"] if a["kind"] == "payload"}
    if not payloads:
        raise ValueError("The lock has no Store payloads.")
    components, selected = [], set()
    for component in catalog["components"]:
        artifact = component.get("artifact", {})
        name = artifact.get("name")
        if name not in payloads:
            continue
        pinned = payloads[name]
        if name in selected or pinned["target"] != "payload/" + name:
            raise ValueError("Duplicate or unsafe catalog artifact: " + name)
        if artifact.get("size") != pinned["bytes"] or artifact.get("sha256") != pinned["sha256"]:
            raise ValueError("Catalog digest/size does not match pinned payload: " + name)
        local = copy.deepcopy(component)
        local["artifact"]["url"] = name
        components.append(local)
        selected.add(name)
    if selected != set(payloads):
        raise ValueError("Pinned payloads are missing from the upstream catalog.")
    catalog["components"] = components
    target = staging / "payload/catalog.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".cache/upstream", help="Verified originals, stored by SHA-256, relative target or basename")
    parser.add_argument("--offline", action="store_true", help="Require all pinned originals in cache; never access the network")
    args = parser.parse_args()
    lock_file = ROOT / "upstream-lock.json"
    lock = load_lock(lock_file)
    resources = ROOT / "resources"
    guide = resources / "guida.html"
    if not guide.is_file():
        raise SystemExit("Missing resources/guida.html from the public source checkout.")
    scratch = ROOT / ".cache"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="resources-", dir=scratch) as temporary:
        staging = Path(temporary)
        for artifact in lock["artifacts"]:
            original = fetch(artifact, args.cache_dir.resolve(), args.offline)
            target = below(staging, artifact["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            if artifact["kind"] == "root_source":
                extract_root(target, staging / "vendor/root")
        make_catalog(lock, staging)
        shutil.copyfile(guide, staging / "guida.html")
        shutil.copyfile(lock_file, staging / "sources/upstream-lock.json")
        manifest = {p.relative_to(staging).as_posix(): sha256(p)
                    for p in sorted(staging.rglob("*")) if p.is_file() and p.name != "integrity.json"
                    and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}}
        # Nothing touches the installed resources until every original has verified.
        # Only prepared files are copied. Unknown local files are never packaged.
        for relative in manifest:
            target = below(resources, relative)
            if target.is_symlink():
                raise ValueError("Resource target is a symlink: " + relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(below(staging, relative), target)
        manifest_path = resources / "integrity.json"
        if manifest_path.is_symlink():
            raise ValueError("Resource manifest is a symlink.")
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(manifest)} verified resource files. No vehicle was contacted.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        raise SystemExit("Resource preparation stopped: " + str(error)) from error
