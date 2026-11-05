"""Regression tests: synthetic fixtures only; no car/SSH/network connections."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import backend


def fake_key(host='169.254.10.20', suffix=b'a'):
    kind = b'ssh-ed25519'
    blob = len(kind).to_bytes(4, 'big')+kind+(32).to_bytes(4, 'big')+suffix*32
    return host+' ssh-ed25519 '+base64.b64encode(blob).decode()+'\n'


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.logs = []
        self.b = backend.Backend(self.root/'resources', self.root/'state', self.logs.append)

    def manifest(self):
        paths = {
            'vendor/root/ssh_enable.py': b'pass',
            'vendor/root/mgu7/diag.py': b'pass',
            'vendor/root/sshd-always-on.sh': b'echo',
            'installer/mgu-install-windows-x64.exe.gz': b'archive',
            'installer/SHA256SUMS': b'checksum',
            'payload/fake@1.0.0.tgz': b'payload',
        }
        artifact = {'name': 'fake@1.0.0.tgz', 'url': 'fake@1.0.0.tgz', 'size': 7,
                    'sha256': hashlib.sha256(b'payload').hexdigest()}
        paths['payload/catalog.json'] = json.dumps({'components': [{'artifact': artifact}]}).encode()
        for name, data in paths.items():
            p = self.b.resource_dir/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        manifest = {name: hashlib.sha256(data).hexdigest() for name, data in paths.items()}
        (self.b.resource_dir/'integrity.json').write_text(json.dumps(manifest))
        return manifest

    def test_reject_non_enet_and_shell_input(self):
        for bad in ('8.8.8.8', 'localhost', '169.254.1.2; rm', '::1', '169.254.0.0', '169.254.255.255'):
            with self.subTest(value=bad), self.assertRaises(backend.BackendError):
                backend.validate_ip(bad)
        self.assertEqual(backend.validate_ip('169.254.10.20'), '169.254.10.20')

    def test_vin_exact(self):
        self.assertEqual(backend.validate_vin('wba00000000000000'), 'WBA00000000000000')
        for bad in ('SHORT', 'WBI00000000000000', 'WBA00000000000000 --force'):
            with self.assertRaises(backend.BackendError):
                backend.validate_vin(bad)

    def test_manifest_valid(self):
        self.manifest()
        self.assertEqual(self.b.verify_files()['count'], 7)

    def test_manifest_rejects_traversal(self):
        m = self.manifest()
        m['../../outside'] = 'a'*64
        (self.b.resource_dir/'integrity.json').write_text(json.dumps(m))
        with self.assertRaises(backend.BackendError):
            self.b.verify_files()

    def test_tampered_payload_stops_before_execution_or_ssh(self):
        self.manifest()
        (self.b.resource_dir/'payload/fake@1.0.0.tgz').write_bytes(b'tampered')
        with patch('backend.is_admin', return_value=True), patch.object(self.b, 'verify_ssh') as ssh, patch('backend.subprocess.Popen') as popen:
            with self.assertRaises(backend.BackendError):
                self.b.install('169.254.10.20', '169.254.10.30', 'key')
            ssh.assert_not_called()
            popen.assert_not_called()

    def test_changed_server_key_is_not_overwritten(self):
        self.b.accept_host('169.254.10.20', fake_key())
        original = self.b.known_hosts.read_text()
        with self.assertRaises(backend.BackendError):
            self.b.accept_host('169.254.10.20', fake_key(suffix=b'b'))
        self.assertEqual(self.b.known_hosts.read_text(), original)

    def test_changed_vehicle_blocks_install_before_ssh(self):
        self.b.last_scan = {'vin': 'WBA00000000000000', 'gateway': '169.254.0.2',
                            'hu_ip': '169.254.10.20', 'local_ip': '169.254.10.30',
                            'supported': True, 'cafd_ok': True}
        changed = dict(self.b.last_scan, vin='WBA00000000000001')
        with patch('backend.is_admin', return_value=True), patch.object(self.b, 'verify_files'), \
             patch.object(self.b, 'scan', return_value=changed), patch.object(self.b, 'verify_ssh') as ssh:
            with self.assertRaises(backend.BackendError):
                self.b.install('169.254.10.20', '169.254.10.30', 'key')
            ssh.assert_not_called()

    def test_other_host_and_injected_key_lines_rejected(self):
        for value in (fake_key('169.254.10.21'), '@cert-authority '+fake_key(), '169.254.10.20 ssh-ed25519 invalid;'):
            with self.assertRaises(backend.BackendError):
                self.b.accept_host('169.254.10.20', value)

    def test_public_key_rejected(self):
        p = self.root/'id_rsa.pub'
        p.write_text('-----BEGIN PRIVATE KEY-----\nfake')
        with self.assertRaises(backend.BackendError):
            backend.validate_key(p)

    def test_demo_never_touches_network_or_processes(self):
        b = backend.Backend(self.root/'resources', self.root/'state', self.logs.append, demo=True)
        with patch('backend.socket.socket', side_effect=AssertionError('network forbidden')), patch('backend.subprocess.run', side_effect=AssertionError('process forbidden')):
            self.assertEqual(len(b.check_pc()['adapters']), 1)
            self.assertTrue(b.scan('169.254.10.30')['demo'])
            self.assertFalse(b.verify_ssh('169.254.10.20', '169.254.10.30', 'missing'))
            self.assertFalse(b.host_fingerprint('169.254.10.20', '169.254.10.30')['changed'])
            for method, args in ((b.install, ('169.254.10.20', '169.254.10.30', 'missing')),
                                 (b.flash, ('WBA00000000000000', '169.254.0.2', '169.254.10.20', '169.254.10.30')),
                                 (b.reboot, ('169.254.10.20', '169.254.10.30', 'missing'))):
                with self.assertRaises(backend.BackendError):
                    method(*args)
        self.assertFalse((self.root/'state').exists())

    def test_flash_target_changes_or_existing_ssh_blocked(self):
        scan = {'vin': 'WBA00000000000000', 'gateway': '169.254.0.2', 'hu_ip': '169.254.10.20',
                'supported': True, 'cafd_ok': True, 'ssh_open': False}
        backend._check_flash_target(scan, scan['vin'], scan['gateway'], scan['hu_ip'])
        for field, val in (('vin', 'WBA00000000000001'), ('gateway', '169.254.0.3'), ('hu_ip', '169.254.10.21'), ('supported', False), ('cafd_ok', False), ('ssh_open', True)):
            changed = dict(scan, **{field: val})
            with self.subTest(field=field), self.assertRaises(backend.BackendError):
                backend._check_flash_target(changed, scan['vin'], scan['gateway'], scan['hu_ip'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
