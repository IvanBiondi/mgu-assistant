"""Pinned resource mirror regression tests; no network or vehicle access."""
from pathlib import Path
import hashlib
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from scripts import prepare_resources as resources


class ResourceBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / "cache"
        self.data = (b"original-one", b"original-two")
        self.artifacts = [
            {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
             "target": f"sources/original-{index}.bin", "kind": "file",
             "url": f"https://github.com/example/project/releases/download/test/{index}"}
            for index, data in enumerate(self.data)
        ]
        self.lock = {"artifacts": self.artifacts}

    def make_bundle(self, entries=None):
        archive = self.root / "bundle.zip"
        if entries is None:
            entries = [(a["sha256"], data) for a, data in zip(self.artifacts, self.data)]
        with warnings.catch_warnings(), zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            warnings.simplefilter("ignore", UserWarning)
            for name, data in entries:
                bundle.writestr(name, data)
        self.lock["resource_bundle"] = {
            "url": "https://github.com/example/project/releases/download/resources/bundle.zip",
            "sha256": resources.sha256(archive), "bytes": archive.stat().st_size,
        }
        return archive

    def assert_rejected_without_cache_entries(self, archive):
        with self.assertRaises((ValueError, zipfile.BadZipFile)):
            resources.install_resource_bundle(archive, self.lock, self.cache)
        for artifact in self.artifacts:
            self.assertFalse((self.cache / artifact["sha256"]).exists())

    def test_verified_bundle_restores_exact_originals(self):
        archive = self.make_bundle()
        resources.install_resource_bundle(archive, self.lock, self.cache)
        for artifact, data in zip(self.artifacts, self.data):
            self.assertEqual((self.cache / artifact["sha256"]).read_bytes(), data)
            self.assertTrue(resources.matches(self.cache / artifact["sha256"], artifact))

    def test_changed_bundle_fails_outer_hash_before_extraction(self):
        archive = self.make_bundle()
        changed = bytearray(archive.read_bytes())
        changed[-1] ^= 1
        archive.write_bytes(changed)
        self.assert_rejected_without_cache_entries(archive)

    def test_outer_byte_mismatch_is_rejected(self):
        archive = self.make_bundle()
        self.lock["resource_bundle"]["bytes"] += 1
        self.assert_rejected_without_cache_entries(archive)

    def test_traversal_member_rejected_even_with_valid_bundle_hash(self):
        archive = self.make_bundle([
            ("../outside", self.data[0]), (self.artifacts[1]["sha256"], self.data[1])])
        self.assert_rejected_without_cache_entries(archive)
        self.assertFalse((self.root / "outside").exists())

    def test_duplicate_or_extra_member_is_rejected(self):
        entries = [(a["sha256"], data) for a, data in zip(self.artifacts, self.data)]
        for extra in (entries[0], ("unexpected-file", b"unknown")):
            with self.subTest(extra=extra[0]):
                archive = self.make_bundle(entries + [extra])
                self.assert_rejected_without_cache_entries(archive)

    def test_nul_aliased_member_name_is_rejected(self):
        aliased_name = self.artifacts[0]["sha256"] + "x"
        archive = self.make_bundle([
            (aliased_name, self.data[0]), (self.artifacts[1]["sha256"], self.data[1])])
        archive.write_bytes(archive.read_bytes().replace(aliased_name.encode(), self.artifacts[0]["sha256"].encode() + b"\0"))
        self.lock["resource_bundle"]["sha256"] = resources.sha256(archive)
        self.assert_rejected_without_cache_entries(archive)

    def test_member_byte_mismatch_rejected_even_with_valid_bundle_hash(self):
        archive = self.make_bundle([
            (self.artifacts[0]["sha256"], b"short"),
            (self.artifacts[1]["sha256"], self.data[1])])
        self.assert_rejected_without_cache_entries(archive)

    def test_member_hash_mismatch_does_not_partially_populate_cache(self):
        archive = self.make_bundle([
            (self.artifacts[0]["sha256"], self.data[0]),
            (self.artifacts[1]["sha256"], b"X" * len(self.data[1]))])
        self.assert_rejected_without_cache_entries(archive)

    def test_symlink_member_rejected_even_with_valid_bundle_hash(self):
        info = zipfile.ZipInfo(self.artifacts[0]["sha256"])
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self.make_bundle([(info, self.data[0]), (self.artifacts[1]["sha256"], self.data[1])])
        self.assert_rejected_without_cache_entries(archive)

    def test_offline_mode_never_fetches_bundle(self):
        self.make_bundle()
        with patch.object(resources, "fetch", side_effect=AssertionError("network forbidden")):
            resources.prepare_bundle_cache(self.lock, self.cache, offline=True)
        self.assertFalse(self.cache.exists())

    def test_existing_verified_cache_does_not_fetch_bundle(self):
        archive = self.make_bundle()
        resources.install_resource_bundle(archive, self.lock, self.cache)
        with patch.object(resources, "fetch", side_effect=AssertionError("network forbidden")):
            resources.prepare_bundle_cache(self.lock, self.cache)

    def test_missing_cache_fetches_pinned_bundle_once(self):
        archive = self.make_bundle()
        with patch.object(resources, "fetch", return_value=archive) as fetch:
            resources.prepare_bundle_cache(self.lock, self.cache)
        fetch.assert_called_once()
        for artifact in self.artifacts:
            self.assertTrue(resources.matches(self.cache / artifact["sha256"], artifact))


if __name__ == "__main__":
    unittest.main()
