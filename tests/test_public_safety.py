"""Public-release regressions. Synthetic identities; no car, SSH or network IO."""
from concurrent.futures import ThreadPoolExecutor
import base64
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import backend


class FlashJournalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.b = backend.Backend(self.root/'resources', self.root/'state', lambda text: None)
        self.scan = dict(vin='WBA00000000000000', gateway='169.254.0.2',
                         hu_ip='169.254.10.20', local_ip='169.254.10.30',
                         supported=True, cafd_ok=True, ssh_open=False)
        self.args = tuple(self.scan[k] for k in ('vin', 'gateway', 'hu_ip', 'local_ip'))
        self.network_guard = patch('backend.socket.socket', side_effect=AssertionError('network forbidden'))
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)
        for guard in (patch('backend.is_admin', return_value=True), patch.object(self.b, 'verify_files')):
            guard.start()
            self.addCleanup(guard.stop)
        scan_guard = patch.object(self.b, 'scan', return_value=self.scan)
        self.read = scan_guard.start()
        self.addCleanup(scan_guard.stop)

    def test_failed_partial_write_is_durable_and_blocks_after_restart(self):
        self.b.last_scan = dict(self.scan)
        self.b._verified_login = ('old',)
        def fail_after_write(argv, *, env_overrides):
            self.assertTrue(self.b.has_flash_attempt(self.scan['vin']))
            record = self.b._read_flash_attempt(self.scan['vin'])
            self.assertEqual(env_overrides[backend.FLASH_ATTEMPT_ENV], record['attempt_id'])
            return 1, 'Flash frames completed; later enrollment readback failed'
        with patch.object(self.b, '_stream', side_effect=fail_after_write) as worker:
            with self.assertRaises(backend.BackendError):
                self.b.flash(*self.args)
            worker.assert_called_once()
        self.assertIsNone(self.b.last_scan)
        self.assertIsNone(self.b._verified_login)
        self.assertEqual(self.b._read_flash_attempt(self.scan['vin'])['state'], 'needs_review')
        reopened = backend.Backend(self.b.resource_dir, self.b.state_dir, lambda text: None)
        with patch.object(reopened, 'scan') as scan, patch.object(reopened, '_stream') as worker:
            with self.assertRaises(backend.BackendError):
                reopened.flash(*self.args)
            scan.assert_not_called()
            worker.assert_not_called()

    def test_process_launch_exception_also_blocks_repeat(self):
        with patch.object(self.b, '_stream', side_effect=OSError('cannot launch')):
            with self.assertRaises(OSError):
                self.b.flash(*self.args)
        self.assertTrue(self.b.has_flash_attempt(self.scan['vin']))
        with patch.object(self.b, '_stream') as worker:
            with self.assertRaises(backend.BackendError):
                self.b.flash(*self.args)
            worker.assert_not_called()

    def test_success_also_blocks_repeat_and_keeps_other_vins_independent(self):
        key = self.b.state_dir/'data/enrollments'/self.scan['vin']/'id_rsa'
        key.parent.mkdir(parents=True)
        key.write_text('-----BEGIN OPENSSH PRIVATE KEY-----\nsynthetic-test-only')
        with patch.object(self.b, '_stream', return_value=(0, 'SSH OK as root:\nDONE: SSH runs with debug mode OFF')):
            self.assertEqual(self.b.flash(*self.args)['key'], str(key))
        self.assertEqual(self.b._read_flash_attempt(self.scan['vin'])['state'], 'confirmed')
        self.assertTrue(self.b.has_flash_attempt(self.scan['vin']))
        self.assertFalse(self.b.has_flash_attempt('WBA00000000000001'))

    def test_read_only_preflight_failure_does_not_reserve_attempt(self):
        self.read.return_value = dict(self.scan, cafd_ok=False)
        with patch.object(self.b, '_stream') as worker:
            with self.assertRaises(backend.BackendError):
                self.b.flash(*self.args)
            worker.assert_not_called()
        self.assertFalse(self.b.has_flash_attempt(self.scan['vin']))

    def test_corrupt_or_partial_journal_fails_closed(self):
        directory = self.b._flash_attempt_dir(self.scan['vin'])
        directory.mkdir(parents=True)
        for content in (None, '{partial', '[]', '{"schema": 8}'):
            with self.subTest(content=content):
                if content is not None:
                    (directory/'attempt.json').write_text(content)
                with patch.object(self.b, '_stream') as worker:
                    with self.assertRaises(backend.BackendError):
                        self.b.flash(*self.args)
                    worker.assert_not_called()

    def test_worker_handoff_consumed_once_and_cannot_target_another_car(self):
        token = self.b._begin_flash_attempt(self.scan)
        for altered in (dict(self.scan, hu_ip='169.254.10.21'), dict(self.scan, local_ip='169.254.10.31')):
            with self.assertRaises(backend.BackendError):
                self.b._claim_flash_attempt(altered, token)
        with self.assertRaises(backend.BackendError):
            self.b._claim_flash_attempt(self.scan, 'wrong-token')
        self.assertEqual(self.b._claim_flash_attempt(self.scan, token), token)
        with self.assertRaises(backend.BackendError):
            self.b._claim_flash_attempt(self.scan, token)
        # Even a process crash between exclusive claiming and its status update
        # cannot let a second worker consume the same reservation.
        record = self.b._read_flash_attempt(self.scan['vin'])
        record['state'] = 'reserved'
        (self.b._flash_attempt_dir(self.scan['vin'])/'attempt.json').write_text(json.dumps(record))
        with self.assertRaises(backend.BackendError):
            self.b._claim_flash_attempt(self.scan, token)

    def test_direct_worker_also_reserves_and_concurrent_parent_reservations_are_exclusive(self):
        def reserve(_):
            other = backend.Backend(self.b.resource_dir, self.b.state_dir, lambda text: None)
            try:
                return other._begin_flash_attempt(self.scan)
            except backend.BackendError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            reservations = list(pool.map(reserve, range(2)))
        self.assertEqual(sum(value is not None for value in reservations), 1)
        with self.assertRaises(backend.BackendError):
            self.b._claim_flash_attempt(self.scan)
        second = dict(self.scan, vin='WBA00000000000001')
        self.assertTrue(self.b._claim_flash_attempt(second))
        self.assertEqual(self.b._read_flash_attempt(second['vin'])['state'], 'worker_started')

    def test_failed_journal_write_prevents_worker(self):
        with patch('backend.os.fsync', side_effect=OSError('disk full')), patch.object(self.b, '_stream') as worker:
            with self.assertRaises(backend.BackendError):
                self.b.flash(*self.args)
            worker.assert_not_called()
        self.assertTrue(self.b.has_flash_attempt(self.scan['vin']))

    def test_previous_attempt_does_not_disable_persistence_recovery(self):
        self.b._begin_flash_attempt(self.scan)
        self.read.return_value = dict(self.scan, ssh_open=True)
        key = self.root/'id_rsa'
        key.write_text('-----BEGIN OPENSSH PRIVATE KEY-----\nsynthetic-test-only')
        with patch.object(self.b, 'verify_ssh'), patch.object(self.b, '_stream', return_value=(0, 'Close routine result: confirmed\nDONE: SSH runs with debug mode OFF')) as worker:
            self.assertTrue(self.b.persist(*self.args, key))
            self.assertEqual(worker.call_args.args[0][worker.call_args.args[0].index('--worker')+1], 'persist')


class FakeUdsReject(Exception):
    def __init__(self, sid=0x22, nrc=0x21):
        super().__init__('synthetic diagnostic rejection')
        self.sid, self.nrc = sid, nrc


class ReadbackRetryTests(unittest.TestCase):
    def test_successful_activation_is_not_repeated_when_readback_is_busy(self):
        calls = []
        responses = iter((FakeUdsReject(), FakeUdsReject(), 'readback accepted'))
        def install():
            calls.append(b'\x31\x01\xa0\xfd')
            return b'\x71\x01\xa0\xfd\x00'
        def readback(client):
            calls.append(b'\x22\x17\x2a')
            response = next(responses)
            if isinstance(response, Exception):
                # The pinned upstream turns UdsReject into EnrollError here.
                try:
                    raise response
                except FakeUdsReject as exc:
                    raise RuntimeError('wrapped by upstream') from exc
            return response
        retry = backend._readback_with_busy_retry(readback, FakeUdsReject, lambda text: None)
        with patch('backend.time.sleep') as sleep:
            self.assertEqual(install(), b'\x71\x01\xa0\xfd\x00')
            self.assertEqual(retry(object()), 'readback accepted')
        self.assertEqual(calls, [b'\x31\x01\xa0\xfd']+[b'\x22\x17\x2a']*3)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(all(call.args == (1,) for call in sleep.call_args_list))

    def test_only_five_total_attempts_then_original_failure(self):
        failure = FakeUdsReject()
        readback = Mock(side_effect=failure)
        retry = backend._readback_with_busy_retry(readback, FakeUdsReject, lambda text: None)
        with patch('backend.time.sleep') as sleep, self.assertRaises(FakeUdsReject) as caught:
            retry(object())
        self.assertIs(caught.exception, failure)
        self.assertEqual(readback.call_count, 5)
        self.assertEqual(sleep.call_count, 4)

    def test_other_service_rejection_timeout_or_message_are_never_retried(self):
        for failure in (FakeUdsReject(0x31, 0x21), FakeUdsReject(0x22, 0x33),
                        TimeoutError('read timed out'), RuntimeError('NRC 0x21 service 0x22')):
            readback = Mock(side_effect=failure)
            retry = backend._readback_with_busy_retry(readback, FakeUdsReject, lambda text: None)
            with self.subTest(failure=failure), patch('backend.time.sleep') as sleep:
                with self.assertRaises(type(failure)) as caught:
                    retry(object())
                self.assertIs(caught.exception, failure)
                readback.assert_called_once()
                sleep.assert_not_called()

    def test_implicit_upstream_exception_context_is_supported(self):
        calls = []
        def readback(client):
            calls.append(client)
            if len(calls) == 1:
                try:
                    raise FakeUdsReject()
                except FakeUdsReject:
                    raise RuntimeError('upstream EnrollError')
            return None
        with patch('backend.time.sleep') as sleep:
            self.assertIsNone(backend._readback_with_busy_retry(readback, FakeUdsReject, lambda text: None)('client'))
        self.assertEqual(calls, ['client', 'client'])
        sleep.assert_called_once_with(1)


class OpenSshSelectionTests(unittest.TestCase):
    def test_windows_system_openssh_wins_before_path_search(self):
        path = MagicMock()
        path.__truediv__.return_value = path
        path.__str__.return_value = 'SYSTEM-OPENSSH'
        path.is_file.return_value = True
        with patch('backend.os.name', 'nt'), patch('backend.Path', return_value=path), \
             patch('backend.shutil.which', return_value='untrusted-PATH-ssh') as which:
            self.assertEqual(backend._binary('ssh'), 'SYSTEM-OPENSSH')
            which.assert_not_called()

    def test_path_fallback_is_used_only_if_system_binary_is_missing(self):
        path = MagicMock()
        path.__truediv__.return_value = path
        path.is_file.return_value = False
        with patch('backend.os.name', 'nt'), patch('backend.Path', return_value=path), \
             patch('backend.shutil.which', return_value='custom-openssh') as which:
            self.assertEqual(backend._binary('ssh-keyscan'), 'custom-openssh')
            which.assert_called_once_with('ssh-keyscan')

    def test_missing_openssh_is_an_explicit_error(self):
        path = MagicMock()
        path.__truediv__.return_value = path
        path.is_file.return_value = False
        with patch('backend.os.name', 'nt'), patch('backend.Path', return_value=path), \
             patch('backend.shutil.which', return_value=None):
            with self.assertRaises(backend.BackendError):
                backend._binary('ssh')


class PersistenceVerificationTests(unittest.TestCase):
    def test_unknown_or_present_debug_state_cannot_report_done(self):
        for state in ({'dtc_debug': None}, {'dtc_debug': True}, {'dtc_debug': 0}, {}, None):
            reader = Mock(return_value=state)
            diag = SimpleNamespace(debug_state=reader)
            messages = []
            def pinned_run(tool):
                result = diag.debug_state(tool.client)
                if result.get('dtc_debug') is not True:
                    messages.append('DONE')
                return True
            tool = SimpleNamespace(client=object())
            wrapped = backend._strict_persist_verification(pinned_run, diag)
            with self.subTest(state=state), self.assertRaises(backend.BackendError):
                wrapped(tool)
            self.assertEqual(messages, [])
            reader.assert_called_once_with(tool.client)
            self.assertIs(diag.debug_state, reader)

    def test_only_explicit_false_allows_verified_persistence_success(self):
        state = {'dtc_debug': False, 'dtcs': []}
        reader = Mock(return_value=state)
        diag = SimpleNamespace(debug_state=reader)
        messages = []
        def pinned_run(tool):
            self.assertIs(diag.debug_state(tool.client), state)
            messages.append('DONE')
            return True
        tool = SimpleNamespace(client=object())
        self.assertTrue(backend._strict_persist_verification(pinned_run, diag)(tool))
        self.assertEqual(messages, ['DONE'])
        reader.assert_called_once_with(tool.client)
        self.assertIs(diag.debug_state, reader)

    def test_early_persistence_failure_preserves_result_without_extra_read(self):
        reader = Mock()
        diag = SimpleNamespace(debug_state=reader)
        self.assertFalse(backend._strict_persist_verification(lambda tool: False, diag)(object()))
        reader.assert_not_called()
        self.assertIs(diag.debug_state, reader)


class LocalKeyPermissionTests(unittest.TestCase):
    def test_windows_acl_uses_current_sid_and_one_verified_descriptor(self):
        path = MagicMock()
        path.resolve.return_value = path
        path.__truediv__.return_value = path
        path.__str__.return_value = "synthetic path '$();` with spaces"
        path.is_file.return_value = True
        with patch('backend.os.name', 'nt'), patch('backend.Path', return_value=path), \
             patch('backend._run', return_value=SimpleNamespace(returncode=0)) as run:
            backend._secure_key_file('synthetic-key')
        argv = run.call_args.args[0]
        self.assertIn('-EncodedCommand', argv)
        script = base64.b64decode(argv[-1]).decode('utf-16-le')
        self.assertIn('WindowsIdentity]::GetCurrent().User', script)
        self.assertIn('[IO.File]::SetAccessControl($p,$acl)', script)
        self.assertIn('[IO.File]::GetAccessControl($p)', script)
        self.assertIn('AreAccessRulesProtected', script)
        self.assertNotIn("synthetic path '$();` with spaces", script)
        self.assertIn(base64.b64encode(str(path).encode('utf-8')).decode('ascii'), script)
        self.assertNotIn('USERNAME', script)

    def test_windows_acl_failure_is_not_silently_ignored(self):
        path = MagicMock()
        path.resolve.return_value = path
        path.__truediv__.return_value = path
        path.__str__.return_value = 'synthetic-key'
        path.is_file.return_value = True
        with patch('backend.os.name', 'nt'), patch('backend.Path', return_value=path), \
             patch('backend._run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(backend.BackendError):
                backend._secure_key_file('synthetic-key')

if __name__ == '__main__':
    unittest.main()
