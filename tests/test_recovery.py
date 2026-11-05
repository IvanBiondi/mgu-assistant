"""Recovery guard tests; no vehicle, SSH commands or network are used."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io
import importlib
import subprocess
import backend


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.b = backend.Backend(self.root/'resources', self.root/'state', lambda text: None)
        self.scan = dict(vin='WBA00000000000000', gateway='169.254.0.2', hu_ip='169.254.10.20',
                         local_ip='169.254.10.30', supported=True, cafd_ok=True, ssh_open=True)
        self.key = self.root/'id_rsa'
        self.key.write_text('-----BEGIN OPENSSH PRIVATE KEY-----\nfixture')
        self.args = (self.scan['vin'], self.scan['gateway'], self.scan['hu_ip'], self.scan['local_ip'], self.key)

    def test_recovery_requires_same_vehicle_valid_coding_open_ssh(self):
        backend._check_persist_target(self.scan, *self.args[:3])
        for field, value in [('vin', 'WBA00000000000001'), ('hu_ip', '169.254.10.21'),
                             ('gateway', '169.254.0.3'), ('supported', False),
                             ('cafd_ok', False), ('ssh_open', False)]:
            with self.subTest(field=field), self.assertRaises(backend.BackendError):
                backend._check_persist_target(dict(self.scan, **{field: value}), *self.args[:3])

    def test_demo_blocks_persistence_and_key_export(self):
        self.b.demo = True
        with patch('backend.socket.socket', side_effect=AssertionError('network')), patch('backend.subprocess.Popen', side_effect=AssertionError('process')):
            with self.assertRaises(backend.BackendError):
                self.b.persist(*self.args)
            with self.assertRaises(backend.BackendError):
                self.b.recover_key(self.args[0])

    def test_persist_worker_is_distinct_and_root_is_rechecked(self):
        with patch('backend.is_admin', return_value=True), patch.object(self.b, 'verify_files'), \
             patch.object(self.b, 'scan', return_value=self.scan), patch.object(self.b, 'verify_ssh') as verify, \
             patch.object(self.b, '_stream', return_value=(0, 'Close routine result: confirmed\nDONE: SSH runs with debug mode OFF')) as stream:
            self.assertTrue(self.b.persist(*self.args))
            argv = stream.call_args.args[0]
            self.assertEqual(argv[argv.index('--worker')+1], 'persist')
            self.assertNotIn('flash', argv)
            self.assertNotIn('enable', argv)
            self.assertIn('--key', argv)
            self.assertEqual(verify.call_count, 2)

    def test_zero_exit_without_persistence_marker_is_failure(self):
        with patch('backend.is_admin', return_value=True), patch.object(self.b, 'verify_files'), \
             patch.object(self.b, 'scan', return_value=self.scan), patch.object(self.b, 'verify_ssh'), \
             patch.object(self.b, '_stream', return_value=(0, 'Persist finished but verification was inconclusive')):
            with self.assertRaises(backend.BackendError):
                self.b.persist(*self.args)

    def test_changed_vehicle_prevents_ssh_and_worker(self):
        with patch('backend.is_admin', return_value=True), patch.object(self.b, 'verify_files'), \
             patch.object(self.b, 'scan', return_value=dict(self.scan, cafd_ok=False)), \
             patch.object(self.b, 'verify_ssh') as verify, patch.object(self.b, '_stream') as stream:
            with self.assertRaises(backend.BackendError):
                self.b.persist(*self.args)
            verify.assert_not_called()
            stream.assert_not_called()

    def test_upstream_persist_flow_with_all_vehicle_io_mocked(self):
        resources = Path(__file__).resolve().parents[1]/'resources'
        b = backend.Backend(resources, self.root/'worker-state', lambda text: None)
        b._load_upstream()
        upstream = importlib.import_module('ssh_enable')
        diag = importlib.import_module('mgu7.diag')
        b.state_dir.mkdir(parents=True)
        b.known_hosts.write_text(self.scan['hu_ip']+' ssh-ed25519 fixture\n')
        calls = []
        def fake_run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, b'0\n' if argv[-1] == 'id -u' else b'', b'')
        def connect(tool):
            tool.mgu_ip = self.scan['hu_ip']
            tool.client = None
        args = dict(worker='persist', vin=self.args[0], gateway=self.args[1], hu_ip=self.args[2],
                    local_ip=self.args[3], key=str(self.key))
        output = io.StringIO()
        with patch('backend.is_admin', return_value=True), patch.object(backend.Backend, 'scan', return_value=self.scan), \
             patch.object(backend.Backend, 'verify_ssh', return_value=True), \
             patch.object(upstream.Tool, 'connect', connect), patch.object(upstream.Tool, 'probe_open', return_value=True), \
             patch.object(upstream.Tool, 'probe', return_value=True), \
             patch.object(upstream.Tool, 'flash', side_effect=AssertionError('FLASH forbidden')), \
             patch.object(upstream.Tool, 'enable', side_effect=AssertionError('ENROLL forbidden')), \
             patch.object(diag, 'close_ssh', return_value='confirmed'), \
             patch.object(diag, 'debug_state', return_value={'dtc_debug': False}), \
             patch('backend.socket.socket', side_effect=AssertionError('network forbidden')), \
             patch('backend.time.sleep'), patch('backend.subprocess.run', side_effect=fake_run), \
             contextlib.redirect_stdout(output):
            self.assertEqual(backend.run_root_worker(args, b.state_dir, resources), 0)
        ssh_calls = [a for a in calls if str(a[0]).lower().endswith('ssh.exe')]
        self.assertEqual(len(ssh_calls), 3)
        for argv in ssh_calls:
            self.assertIn('StrictHostKeyChecking=yes', argv)
            self.assertNotIn('StrictHostKeyChecking=no', argv)
            self.assertIn(self.scan['local_ip'], argv)
        self.assertIn('sshd-always-on.sh', ssh_calls[-1][-1])
        self.assertIn('DONE: SSH runs with debug mode OFF', output.getvalue())


if __name__ == '__main__':
    unittest.main()
