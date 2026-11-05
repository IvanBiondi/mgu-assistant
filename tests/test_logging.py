"""Windows pipe regression: no network, vehicle or flash calls."""
import io
import sys
import unittest
from unittest.mock import patch

from main import _restore_worker_streams


class WorkerLoggingTests(unittest.TestCase):
    def test_existing_cp1252_pipes_become_utf8(self):
        raw_out, raw_err = io.BytesIO(), io.BytesIO()
        out = io.TextIOWrapper(raw_out, encoding='cp1252', errors='strict')
        err = io.TextIOWrapper(raw_err, encoding='cp1252', errors='strict')
        with patch.object(sys, 'stdout', out), patch.object(sys, 'stderr', err):
            _restore_worker_streams()
            print('Frame 1/174; 0%; transfer part 0; TX 0xF4 → 0x63 • 2 bytes', flush=True)
            print('Integrità à → • ✓', file=sys.stderr, flush=True)
        self.assertIn('0xF4 → 0x63 •', raw_out.getvalue().decode('utf-8'))
        self.assertEqual(raw_err.getvalue().decode('utf-8').splitlines(), ['Integrità à → • ✓'])

    def test_stream_setup_is_idempotent_and_surrogate_safe(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='cp1252', errors='strict')
        with patch.object(sys, 'stdout', stream), patch.object(sys, 'stderr', stream):
            _restore_worker_streams()
            _restore_worker_streams()
            print('diagnostic \udcff →', flush=True)
        self.assertEqual(raw.getvalue().decode('utf-8').splitlines(), ['diagnostic \\udcff →'])


if __name__ == '__main__':
    unittest.main()
