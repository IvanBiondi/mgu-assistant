"""UI state regressions without opening a window or contacting a vehicle."""
import queue
import unittest
from unittest.mock import Mock, patch
from main import MGUApp


class UIStateTests(unittest.TestCase):
    def app(self):
        app = MGUApp.__new__(MGUApp)
        app.closed = False
        app.busy = app.write_busy = True
        app.events = queue.Queue()
        app.root = Mock()
        app.progress = Mock()
        app.status = Mock()
        app.hu_text = Mock()
        app.root_text = Mock()
        app.coding_ok = Mock()
        app.svk_table = Mock()
        app.svk_table.get_children.return_value = []
        app._log = Mock()
        app._refresh = Mock()
        app.scan_result = {'vin': 'WBA00000000000000'}
        app.scan_time = 100
        app.ssh_verified = ('old-identity',)
        app.host_accepted = ('old-host',)
        app.install_success = app.flash_success = True
        return app

    def test_failed_write_invalidates_scan_root_coding_and_install(self):
        app = self.app()
        app.events.put(('error', ('Test write', 'simulated interruption')))
        with patch('main.messagebox.showerror'):
            app._poll()
        self.assertIsNone(app.scan_result)
        self.assertIsNone(app.ssh_verified)
        self.assertIsNone(app.host_accepted)
        self.assertFalse(app.install_success)
        app.coding_ok.set.assert_called_with(False)
        self.assertFalse(app.busy)

    def test_unusable_write_result_invalidates_authorization(self):
        app = self.app()
        app.events.put(('success', ('Test write', {}, Mock(side_effect=ValueError('bad result')))))
        with patch('main.messagebox.showerror'):
            app._poll()
        self.assertIsNone(app.scan_result)
        self.assertIsNone(app.ssh_verified)

    def test_journal_blocks_flash_before_confirmation(self):
        app = self.app()
        app.demo = False
        app._scan_ready = Mock(return_value=True)
        app._prerequisites = Mock(return_value=True)
        app._root_seen = Mock(return_value=False)
        app.backend = Mock()
        app.backend.has_flash_attempt.return_value = True
        with patch('main.simpledialog.askstring') as prompt:
            app.flash()
        prompt.assert_not_called()
        app.backend.flash.assert_not_called()

    def test_log_disk_error_does_not_break_polling_or_cancel_worker(self):
        app = self.app()
        del app._log
        app.log_error = False
        app.log_file = Mock()
        app.log_file.write.side_effect = OSError('disk full')
        app.log_widget = Mock()
        app._log('Progress from active worker')
        self.assertTrue(app.log_error)
        self.assertTrue(app.busy)
        self.assertTrue(app.write_busy)
        self.assertIn('REGISTRO NON SCRIVIBILE', app.log_widget.insert.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
