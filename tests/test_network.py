"""Synthetic ENET discovery: no Windows commands, sockets or vehicles are used."""
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import backend


class NetworkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.b = backend.Backend(root / 'resources', root / 'state', lambda _: None)

    def test_private_ranges_and_link_local_are_allowed(self):
        for value in ('169.254.10.20', '192.168.1.20', '10.2.3.4', '172.16.1.2', '172.31.255.254'):
            self.assertEqual(backend.validate_ip(value), value)
        for value in ('8.8.8.8', '127.0.0.1', '0.0.0.0', '224.0.0.1', '255.255.255.255',
                      '100.64.1.2', '192.0.2.1', '172.15.1.2', '172.32.1.2', '::1',
                      '192.168.1.2;echo unsafe', 'localhost'):
            with self.subTest(value=value), self.assertRaises(backend.BackendError):
                backend.validate_ip(value)

    def test_actual_prefix_controls_broadcast_and_host_validation(self):
        network = backend.adapter_network('192.168.17.40', 20)
        self.assertEqual(str(network.broadcast_address), '192.168.31.255')
        # .0 and .255 are valid hosts in some subnets; do not assume /24.
        self.assertEqual(backend.validate_peer('192.168.18.0', network, '192.168.17.40'), '192.168.18.0')
        for value in ('192.168.16.0', '192.168.31.255', '192.168.32.1', '192.168.17.40'):
            with self.assertRaises(backend.BackendError):
                backend.validate_peer(value, network, '192.168.17.40')

    def test_invalid_or_excessively_broad_prefix_is_rejected(self):
        for prefix in (None, '24', True, 0, 15, 31, 32, 33):
            with self.subTest(prefix=prefix), self.assertRaises(backend.BackendError):
                backend.adapter_network('192.168.1.10', prefix)
        for address in ('192.168.1.0', '192.168.1.255'):
            with self.assertRaises(backend.BackendError):
                backend.adapter_network(address, 24)

    def test_windows_adapter_inventory_keeps_private_addresses_and_prefixes(self):
        rows = [dict(name='Ethernet', index=n, ip=ip, prefix_length=prefix) for n, (ip, prefix)
                in enumerate([('169.254.1.30', 16), ('192.168.8.30', 24), ('10.2.3.4', 8),
                              ('172.20.1.30', 16), ('8.8.8.8', 24), ('192.168.1.255', 24)])]
        with patch('backend._run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(rows), stderr='')) as run:
            self.assertEqual(backend.enet_adapters(), rows[:4])
            self.assertIn('PrefixLength', run.call_args.args[0][-1])

    def test_windows_adapter_inventory_accepts_empty_and_single_json(self):
        row = dict(name='ENET', index=7, ip='192.168.8.30', prefix_length=24)
        for value, expected in (('', []), ('[]', []), (json.dumps(row), [row])):
            with patch('backend._run', return_value=SimpleNamespace(returncode=0, stdout=value, stderr='')):
                self.assertEqual(backend.enet_adapters(), expected)

    def scan(self, local, prefix, replies, hu):
        class Client:
            def __init__(self, gateway):
                self.gateway, self.port = gateway, 6801
            def close(self):
                pass
        record = SimpleNamespace(name='CAFD', version_hex=lambda: '00003E52', trip_text=lambda: '006.036.030')
        svk = SimpleNamespace(records=[record], is_supported_mgu=lambda: True)
        discovery = SimpleNamespace(PROBE=b'probe', DISCOVERY_PORT=6811, parse_reply=lambda data: data.decode())
        diag = SimpleNamespace(read_svk=MagicMock(return_value=svk), read_mgu_ip=MagicMock(return_value=(hu,)))
        udp = MagicMock()
        udp.recvfrom.side_effect = replies + [socket.timeout()] * 10
        row = dict(name='ENET', index=7, ip=local, prefix_length=prefix)
        with patch.object(self.b, 'verify_files'), patch('backend.enet_adapters', return_value=[row]), \
             patch.object(self.b, '_load_upstream', return_value=(discovery, SimpleNamespace(EnetClient=Client, MGU=0x63), diag)), \
             patch('backend.socket.socket') as socket_factory, patch('backend.socket.create_connection') as connect, \
             patch('backend.time.monotonic', side_effect=[0, .1, .2, .3, .4, .5, 3]), \
             patch.object(self.b, '_port', return_value=False) as port:
            socket_factory.return_value.__enter__.return_value = udp
            self.udp, self.connect, self.port = udp, connect, port
            return self.b.scan(local)

    def test_discovery_broadcasts_on_selected_subnet_and_binds_diagnostics(self):
        for local, prefix, gateway, hu, broadcast in (
                ('169.254.10.30', 16, '169.254.0.2', '169.254.10.20', '169.254.255.255'),
                ('192.168.17.40', 20, '192.168.18.1', '192.168.18.20', '192.168.31.255'),
                ('10.2.3.40', 24, '10.2.3.1', '10.2.3.20', '10.2.3.255'),
                ('172.20.3.40', 24, '172.20.3.1', '172.20.3.20', '172.20.3.255')):
            with self.subTest(local=local):
                result = self.scan(local, prefix, [(b'WBA00000000000000', (gateway, 6811))], hu)
                self.assertEqual(result['hu_ip'], hu)
                self.udp.bind.assert_called_once_with((local, 0))
                self.udp.sendto.assert_called_once_with(b'probe', (broadcast, 6811))
                self.connect.assert_called_once_with((gateway, 6801), timeout=4, source_address=(local, 0))
                self.port.assert_called_once_with(hu, local)

    def test_unsuitable_discovery_replies_are_ignored(self):
        replies = [(b'WBA00000000000000', (ip, 6811)) for ip in (
            '8.8.8.8', '192.168.2.1', '192.168.1.0', '192.168.1.255', '192.168.1.30')]
        with self.assertRaisesRegex(backend.BackendError, 'No ENET gateway'):
            self.scan('192.168.1.30', 24, replies, '192.168.1.20')
        self.connect.assert_not_called()

    def test_two_gateways_still_block_even_with_same_vin(self):
        replies = [(b'WBA00000000000000', (ip, 6811)) for ip in ('192.168.1.1', '192.168.1.2')]
        with self.assertRaisesRegex(backend.BackendError, 'Multiple gateways'):
            self.scan('192.168.1.30', 24, replies, '192.168.1.20')
        self.connect.assert_not_called()

    def test_hu_outside_subnet_is_blocked_before_ssh_probe(self):
        for hu in ('192.168.2.20', '8.8.8.8', '192.168.1.0', '192.168.1.255', '192.168.1.30'):
            with self.subTest(hu=hu), self.assertRaises(backend.BackendError):
                self.scan('192.168.1.30', 24, [(b'WBA00000000000000', ('192.168.1.1', 6811))], hu)
            self.port.assert_not_called()

    def test_missing_or_duplicate_local_address_blocks_before_network(self):
        row = dict(ip='192.168.1.30', prefix_length=24)
        for rows in ([], [row, row]):
            with patch.object(self.b, 'verify_files'), patch('backend.enet_adapters', return_value=rows), \
                 patch('backend.socket.socket') as sockets, self.assertRaises(backend.BackendError):
                self.b.scan('192.168.1.30')
            sockets.assert_not_called()


if __name__ == '__main__':
    unittest.main()
