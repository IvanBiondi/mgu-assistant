"""Local backend for MGU Assistant. No vehicle operations occur on import.

The GUI owns human confirmations. Every write additionally checks its prerequisites
here. The root worker is isolated and calls the unmodified, pinned upstream tool.
"""
from __future__ import annotations

import base64
import ctypes
from datetime import datetime, timezone
import gzip
import hashlib
import importlib
import ipaddress
import json
import os
from pathlib import Path
import re
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Callable
import uuid

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
VIN_RE = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$')
ROOT_COMMIT = 'a4aa8932f1a61e784b761ea04ecc64f82c87a0d3'
FLASH_ATTEMPT_ENV = 'MGU_ASSISTANT_FLASH_ATTEMPT'


class BackendError(RuntimeError):
    pass


def validate_ip(value: str) -> str:
    try:
        ip = ipaddress.ip_address(str(value).strip())
    except ValueError as exc:
        raise BackendError('Inserire un indirizzo IPv4 ENET valido.') from exc
    if ip.version != 4 or not ip.is_link_local or int(ip) & 0xFFFF in (0, 0xFFFF):
        raise BackendError('Sono ammessi soltanto indirizzi ENET 169.254.x.x.')
    return str(ip)


def validate_vin(value: str) -> str:
    value = str(value).strip().upper()
    if not VIN_RE.fullmatch(value):
        raise BackendError('Il VIN deve avere 17 caratteri validi.')
    return value


def validate_key(value) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() in ('.pub', '.ppk') or path.name.endswith('.pub.pem'):
        raise BackendError('Selezionare la chiave PRIVATA OpenSSH id_rsa, non .pub o .ppk.')
    if path.stat().st_size > 65536:
        raise BackendError('Il file selezionato non sembra una chiave privata.')
    first = path.read_bytes()[:100]
    if b'PRIVATE KEY-----' not in first:
        raise BackendError('Il file non contiene una chiave privata riconoscibile.')
    return path


def is_admin() -> bool:
    if os.name != 'nt':
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _binary(name: str) -> str:
    result = None
    if os.name == 'nt':
        candidate = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'OpenSSH' / (name + '.exe')
        if candidate.is_file():
            result = str(candidate)
    if not result:
        result = shutil.which(name) or shutil.which(name + '.exe')
    if not result:
        raise BackendError(f'{name} non disponibile. Installare Client OpenSSH nelle funzionalità facoltative di Windows.')
    return result


def _run(argv, *, timeout=30, input=None):
    try:
        return subprocess.run([str(a) for a in argv], input=input, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, encoding='utf-8', errors='replace',
                              timeout=timeout, creationflags=CREATE_NO_WINDOW, shell=False)
    except subprocess.TimeoutExpired as exc:
        raise BackendError('Operazione di lettura scaduta. Nessuna riparazione automatica avviata.') from exc


def _secure_key_file(path):
    """Protect app-generated key copies; never change a user's selected key.

    Windows applies owner + one explicit current-user ACE together, then checks
    the resulting ACL. This avoids removing inheritance after a failed grant.
    """
    target = Path(path).resolve()
    if not target.is_file():
        raise BackendError('La copia locale della chiave non esiste: autorizzazioni non applicate.')
    if os.name != 'nt':
        target.chmod(0o600)
        return
    encoded_path = base64.b64encode(str(target).encode('utf-8')).decode('ascii')
    script = """$ErrorActionPreference='Stop'
$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PATH__'))
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$acl=[Security.AccessControl.FileSecurity]::new()
$acl.SetOwner($sid)
$acl.SetAccessRuleProtection($true,$false)
$rule=[Security.AccessControl.FileSystemAccessRule]::new($sid,[Security.AccessControl.FileSystemRights]::FullControl,[Security.AccessControl.AccessControlType]::Allow)
$acl.AddAccessRule($rule)
[IO.File]::SetAccessControl($p,$acl)
$actual=[IO.File]::GetAccessControl($p)
$owner=$actual.GetOwner([Security.Principal.SecurityIdentifier]).Value
$rules=@($actual.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
if($owner -ne $sid.Value -or -not $actual.AreAccessRulesProtected -or $rules.Count -ne 1){throw 'ACL verification failed'}
$r=$rules[0]
if($r.IdentityReference.Value -ne $sid.Value -or $r.IsInherited -or $r.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or $r.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl){throw 'ACL verification failed'}
""".replace('__PATH__', encoded_path)
    command = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = _run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', command], timeout=20)
        if result.returncode:
            raise BackendError('Verifica ACL non riuscita.')
    except (OSError, BackendError) as exc:
        raise BackendError('Autorizzazioni della copia locale della chiave non confermate. Nessuna connessione SSH deve usare questa copia finché il controllo non riesce.') from exc


def _key_lines(host: str, text: str) -> tuple[list[str], list[str]]:
    """Validate keyscan output; never accept options/markers/another host."""
    valid, prints = [], []
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) != 3 or parts[0] != host or parts[1] not in ('ssh-rsa', 'ssh-ed25519', 'ecdsa-sha2-nistp256'):
            raise BackendError('Risposta chiave server non valida o indirizzata a un altro host.')
        try:
            blob = base64.b64decode(parts[2], validate=True)
            n = int.from_bytes(blob[:4], 'big')
            if not 1 <= n <= 64 or blob[4:4+n].decode('ascii') != parts[1] or len(blob) < n+12:
                raise ValueError('SSH key type')
        except (ValueError, UnicodeError) as exc:
            raise BackendError('Chiave pubblica server malformata.') from exc
        normalized = ' '.join(parts)
        if normalized not in valid:
            valid.append(normalized)
            fp = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
            prints.append(f'{parts[1]} SHA256:{fp}')
    if not valid:
        raise BackendError('Nessuna chiave server ricevuta dalla HU.')
    return valid, prints


class _BoundKeyScan:
    """Loopback SSH-keyscan relay; every outbound socket binds the selected ENET IP."""
    def __init__(self, target, local):
        self.target, self.local = target, local
        self.stop = threading.Event()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(8)
        self.listener.settimeout(.2)
        self.port = self.listener.getsockname()[1]
        self.threads = []

    def __enter__(self):
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()
        return self

    def _accept(self):
        while not self.stop.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._relay, args=(client,), daemon=True)
            self.threads.append(t)
            t.start()

    def _relay(self, client):
        remote = None
        try:
            remote = socket.create_connection((self.target, 22), timeout=4,
                                              source_address=(self.local, 0))
            deadline = time.monotonic()+12
            while not self.stop.is_set() and time.monotonic() < deadline:
                reads, _, _ = select.select([client, remote], [], [], .2)
                for src in reads:
                    data = src.recv(65536)
                    if not data:
                        return
                    (remote if src is client else client).sendall(data)
        except OSError:
            pass
        finally:
            client.close()
            if remote:
                remote.close()

    def __exit__(self, *unused):
        self.stop.set()
        self.listener.close()
        self.thread.join(timeout=1)
        for thread in self.threads:
            thread.join(timeout=.3)


class Backend:
    def __init__(self, resource_dir: Path, state_dir: Path, log: Callable[[str], None], demo=False):
        self.resource_dir = Path(resource_dir).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.log = log
        self.demo = bool(demo)
        self.last_scan = None
        self._verified_login = None

    @property
    def known_hosts(self):
        return self.state_dir / 'known_hosts'

    def _write_guard(self):
        if self.demo:
            raise BackendError('Modalità dimostrativa: tutte le scritture sulla vettura sono disabilitate.')
        if not is_admin():
            raise BackendError('Chiudere e avviare MGU Assistant con Esegui come amministratore prima di modificare la HU.')

    def _flash_attempt_dir(self, vin):
        return self.state_dir/'flash-attempts'/validate_vin(vin)

    def has_flash_attempt(self, vin):
        """A missing/corrupt journal inside an existing reservation still blocks flash."""
        directory = self._flash_attempt_dir(vin)
        return directory.exists() or directory.is_symlink()

    def _begin_flash_attempt(self, scan):
        """Reserve exactly once before launching a writer; never remove this guard."""
        directory = self._flash_attempt_dir(scan['vin'])
        record = {'schema': 1, 'attempt_id': uuid.uuid4().hex, 'state': 'reserved',
                  'created_utc': datetime.now(timezone.utc).isoformat(),
                  **{name: scan[name] for name in ('vin', 'gateway', 'hu_ip', 'local_ip')}}
        try:
            directory.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive directory creation prevents two GUI/worker instances racing.
            directory.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise BackendError('Esiste già un tentativo di sblocco per questa vettura. Nuovo flash bloccato anche se SSH è chiuso. Verificare l’esito precedente e usare il recupero della chiave o la persistenza quando appropriato.') from exc
        except OSError as exc:
            raise BackendError('Impossibile registrare il tentativo: nessun flash avviato.') from exc
        try:
            with (directory/'attempt.json').open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            # Even a partially written reservation remains blocking after restart.
            raise BackendError('Registro del tentativo non salvato: nessun flash avviato. Il blocco locale resta attivo e richiede verifica.') from exc
        return record['attempt_id']

    def _read_flash_attempt(self, vin):
        try:
            record = json.loads((self._flash_attempt_dir(vin)/'attempt.json').read_text(encoding='utf-8'))
            if not isinstance(record, dict) or record.get('schema') != 1 or record.get('vin') != validate_vin(vin):
                raise ValueError('invalid journal')
            return record
        except (OSError, ValueError) as exc:
            raise BackendError('Registro del tentativo assente o non leggibile: nuovo flash bloccato.') from exc

    def _update_flash_attempt(self, vin, attempt_id, state, **details):
        record = self._read_flash_attempt(vin)
        if record.get('attempt_id') != attempt_id:
            raise BackendError('Il registro del tentativo è cambiato: operazione bloccata.')
        record.update(state=state, updated_utc=datetime.now(timezone.utc).isoformat(), **details)
        directory = self._flash_attempt_dir(vin)
        temporary = directory/('attempt-'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, directory/'attempt.json')
        finally:
            temporary.unlink(missing_ok=True)

    def _note_flash_result(self, vin, attempt_id, state, **details):
        # A status/logging failure must not erase the durable reservation or mask
        # the outcome of a vehicle write that may already have completed.
        try:
            self._update_flash_attempt(vin, attempt_id, state, **details)
        except (OSError, BackendError):
            try:
                self.log('Esito non aggiornabile nel registro locale; il blocco del nuovo flash resta attivo.')
            except Exception:
                pass

    def _claim_flash_attempt(self, scan, attempt_id=None):
        # Direct worker invocation receives the same once-only guard as the GUI.
        attempt_id = attempt_id or self._begin_flash_attempt(scan)
        record = self._read_flash_attempt(scan['vin'])
        if record.get('attempt_id') != attempt_id or record.get('state') != 'reserved' or any(
                record.get(field) != scan.get(field) for field in ('vin', 'gateway', 'hu_ip', 'local_ip')):
            raise BackendError('Tentativo di flash non autorizzato dal registro corrente o già avviato.')
        try:
            with (self._flash_attempt_dir(scan['vin'])/'worker-claimed').open('x', encoding='ascii') as stream:
                stream.write(attempt_id+'\n')
                stream.flush()
                os.fsync(stream.fileno())
            self._update_flash_attempt(scan['vin'], attempt_id, 'worker_started')
        except (OSError, BackendError) as exc:
            raise BackendError('Tentativo già consumato o registro non aggiornabile: nuovo flash bloccato.') from exc
        return attempt_id

    def verify_files(self) -> dict:
        manifest_path = self.resource_dir/'integrity.json'
        if not manifest_path.is_file():
            raise BackendError('Manifest di integrità mancante: estrarre tutto il pacchetto.')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        files = manifest.get('files', manifest)
        if not isinstance(files, dict) or not files:
            raise BackendError('Manifest di integrità non valido.')
        essential = ('vendor/root/ssh_enable.py', 'vendor/root/mgu7/diag.py',
                     'vendor/root/sshd-always-on.sh', 'installer/mgu-install-windows-x64.exe.gz',
                     'installer/SHA256SUMS', 'payload/catalog.json')
        if any(name not in files for name in essential):
            raise BackendError('Il manifest non comprende i componenti essenziali.')
        for relative, expected in files.items():
            path = (self.resource_dir / relative).resolve()
            if not path.is_relative_to(self.resource_dir) or not re.fullmatch('[a-fA-F0-9]{64}', str(expected)):
                raise BackendError('Percorso o digest non valido nel manifest.')
            if not path.is_file() or path.is_symlink() or _sha(path) != str(expected).lower():
                raise BackendError(f'File mancante o SHA256 diverso: {relative}. Nessun programma eseguito.')
        catalog = json.loads((self.resource_dir/'payload/catalog.json').read_text(encoding='utf-8-sig'))
        for component in catalog['components']:
            artifact = component['artifact']
            relative = artifact.get('url') or artifact['name']
            if '/' in relative or '\\' in relative or relative in ('.', '..'):
                raise BackendError('Il catalogo offline contiene un percorso non locale.')
            path = self.resource_dir/'payload'/relative
            if 'payload/'+relative not in files or path.stat().st_size != artifact['size'] or _sha(path) != artifact['sha256']:
                raise BackendError('Artefatto del catalogo non verificato: '+relative)
        self.log(f'Integrità locale verificata: {len(files)} file. Gli hash non certificano compatibilità o sicurezza del firmware.')
        return {'ok': True, 'count': len(files), 'components': len(catalog['components'])}

    def _load_upstream(self):
        vendor = self.resource_dir/'vendor/root'
        if str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
        return tuple(importlib.import_module(n) for n in ('mgu7.discovery', 'mgu7.hsfz', 'mgu7.diag'))

    def self_check(self):
        result = self.verify_files()
        discovery, hsfz, diag = self._load_upstream()
        ident = importlib.import_module('mgu7.identity')
        assets = importlib.import_module('mgu7.assets')
        store = assets.Assets(str(self.resource_dir/'vendor/root/data/assets'))
        cert = store.cert()
        if not store.raw(7) or not cert:
            raise BackendError('Asset upstream incompleti.')
        from cryptography.hazmat.primitives import serialization
        serialization.load_pem_private_key(store.raw(5), password=None)
        svk = diag.parse_svk(bytes.fromhex('62 F1 01 06 00 00 3F 36 01 02 03'))
        if not svk.is_supported_mgu():
            raise BackendError('Autoverifica parser fallita.')
        result.update({'upstream': ROOT_COMMIT, 'crypto': True, 'no_vehicle_access': True})
        return result

    def check_pc(self) -> dict:
        if self.demo:
            return {'ssh': 'DEMO OpenSSH', 'admin': False, 'adapters': [{'name': 'Ethernet dimostrativa', 'index': 12, 'ip': '169.254.10.30'}]}
        try:
            ssh = _binary('ssh')
            version = _run([ssh, '-V'], timeout=5)
            ssh_text = (version.stdout + version.stderr).strip()
        except BackendError:
            ssh_text = ''
        command = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $ErrorActionPreference='Stop'; $a=@(Get-NetAdapter | Where-Object Status -eq 'Up'); @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -like '169.254.*' -and $_.InterfaceIndex -in $a.ifIndex} | ForEach-Object {[pscustomobject]@{name=$_.InterfaceAlias;index=$_.InterfaceIndex;ip=$_.IPAddress}}) | ConvertTo-Json -Compress"
        ps = str(Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe')
        result = _run([ps, '-NoProfile', '-NonInteractive', '-Command', command], timeout=25)
        if result.returncode:
            raise BackendError('Windows non consente la lettura delle schede. Avviare come amministratore. '+result.stderr.strip())
        parsed = json.loads(result.stdout.lstrip('\ufeff').strip() or '[]')
        adapters = parsed if isinstance(parsed, list) else [parsed]
        self.log(f'OpenSSH: {ssh_text or "non trovato"}; schede ENET attive: {len(adapters)}.')
        return {'ssh': ssh_text, 'admin': is_admin(), 'adapters': adapters}

    def scan(self, local_ip) -> dict:
        local_ip = validate_ip(local_ip)
        self._verified_login = None
        if self.demo:
            result = {'vin': 'WBA00000000000000', 'gateway': '169.254.0.2', 'hu_ip': '169.254.10.20',
                      'svk': [{'type': 'BTLD', 'id': '00003F36', 'version': '001.002.003'}, {'type': 'CAFD', 'id': '00003E52', 'version': '001.002.003'}],
                      'supported': True, 'cafd_ok': True, 'ssh_open': False, 'local_ip': local_ip, 'demo': True}
            self.last_scan = result
            self.log('DEMO: dati di esempio; nessun pacchetto inviato alla rete.')
            return result
        self.verify_files()
        discovery, hsfz, diag = self._load_upstream()
        found = {}
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.bind((local_ip, 0))
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp.settimeout(.2)
            udp.sendto(discovery.PROBE, ('169.254.255.255', discovery.DISCOVERY_PORT))
            end = time.monotonic()+2.5
            while time.monotonic() < end:
                try:
                    data, address = udp.recvfrom(4096)
                except socket.timeout:
                    continue
                vin = discovery.parse_reply(data)
                if vin and VIN_RE.fullmatch(vin) and address[0].startswith('169.254.'):
                    found[address[0]] = vin
        if len(found) != 1:
            raise BackendError('Nessun gateway ENET rilevato.' if not found else 'Più gateway rilevati: interrompere e collegare soltanto la propria auto.')
        gateway, vin = next(iter(found.items()))
        class BoundReadClient(hsfz.EnetClient):
            def connect(self):
                self.close()
                self.sock = socket.create_connection((self.gateway, self.port), timeout=4,
                                                     source_address=(local_ip, 0))
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.sock.settimeout(5)
                self.buf = b''
            def request(self, destination, request, profile):
                if destination != hsfz.MGU or request not in (b'\x22\xf1\x01', b'\x22\x17\x2a'):
                    raise BackendError('Richiesta fuori dalla lista di sola lettura: bloccata.')
                return super().request(destination, request, profile)
        client = BoundReadClient(gateway)
        client.connect()
        try:
            svk = diag.read_svk(client)
            hu_ip = validate_ip(diag.read_mgu_ip(client)[0])
        finally:
            client.close()
        records = [{'type': r.name, 'id': r.version_hex(), 'version': r.trip_text()} for r in svk.records]
        result = {'vin': vin, 'gateway': gateway, 'hu_ip': hu_ip, 'svk': records,
                  'supported': svk.is_supported_mgu(),
                  'cafd_ok': any(r['type'] == 'CAFD' and r['id'] != 'FFFFFFFF' for r in records),
                  'ssh_open': self._port(hu_ip, local_ip), 'local_ip': local_ip}
        self.last_scan = result
        self.log(f'VIN {vin}; HU {hu_ip}; gateway {gateway}; SSH aperto: {result["ssh_open"]}.')
        self.log('Filtro MGU superato: '+str(result['supported'])+'. Non è una certificazione del firmware.')
        for r in records:
            self.log(f'{r["type"]} {r["id"]} {r["version"]}')
        return result

    @staticmethod
    def _port(host, local, timeout=3):
        try:
            with socket.create_connection((host, 22), timeout=timeout, source_address=(local, 0)):
                return True
        except OSError:
            return False

    def host_fingerprint(self, hu_ip, local_ip):
        hu_ip, local_ip = validate_ip(hu_ip), validate_ip(local_ip)
        if self.demo:
            return {'fingerprints': ['DEMO: nessuna chiave reale acquisita'], 'key_lines': '', 'changed': False, 'already_trusted': False}
        with _BoundKeyScan(hu_ip, local_ip) as relay:
            proc = _run([_binary('ssh-keyscan'), '-T', '4', '-p', str(relay.port), '-t', 'rsa,ecdsa,ed25519', '127.0.0.1'], timeout=18)
        lines = []
        for line in proc.stdout.splitlines():
            p = line.split()
            if len(p) == 3 and not line.startswith('#'):
                lines.append(hu_ip+' '+p[1]+' '+p[2])
        normalized, prints = _key_lines(hu_ip, '\n'.join(lines))
        existing = self._existing(hu_ip)
        changed = bool(existing) and set(existing) != set(normalized)
        return {'fingerprints': prints, 'key_lines': '\n'.join(normalized)+'\n',
                'changed': changed, 'already_trusted': bool(existing) and not changed}

    def _existing(self, host):
        if not self.known_hosts.is_file():
            return []
        return [line.strip() for line in self.known_hosts.read_text(encoding='utf-8').splitlines()
                if line.split() and line.split()[0] == host]

    def accept_host(self, hu_ip, key_lines):
        hu_ip = validate_ip(hu_ip)
        if self.demo:
            self.log('DEMO: nessuna chiave salvata.')
            return
        lines, prints = _key_lines(hu_ip, key_lines)
        existing = self._existing(hu_ip)
        if existing and set(existing) != set(lines):
            raise BackendError('La chiave server è cambiata. Non viene sovrascritta: verificare la causa prima di continuare.')
        if not existing:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with self.known_hosts.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write('\n'.join(lines)+'\n')
        self.log('Chiave server memorizzata dopo conferma. Questo è trust al primo collegamento, non una certificazione BMW.')

    def _ssh_args(self, hu_ip, local_ip, key):
        hu_ip, local_ip = validate_ip(hu_ip), validate_ip(local_ip)
        key = validate_key(key)
        if not self._existing(hu_ip):
            raise BackendError('Acquisire e confermare prima la fingerprint della HU.')
        kh = str(self.known_hosts).replace('\\', '/')
        return [_binary('ssh'), '-F', 'NUL' if os.name == 'nt' else '/dev/null', '-b', local_ip, '-p', '22', '-i', str(key),
                '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'PasswordAuthentication=no',
                '-o', 'KbdInteractiveAuthentication=no', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'UserKnownHostsFile="'+kh+'"', '-o', 'GlobalKnownHostsFile="'+kh+'"',
                '-o', 'UpdateHostKeys=no', '-o', 'ConnectTimeout=8', '-o', 'ConnectionAttempts=1',
                '-o', 'HostKeyAlgorithms=+ssh-rsa', '-o', 'PubkeyAcceptedAlgorithms=+ssh-rsa',
                'root@'+hu_ip]

    def verify_ssh(self, hu_ip, local_ip, key):
        if self.demo:
            self.log('DEMO: il login root reale non è stato verificato.')
            return False
        args = self._ssh_args(hu_ip, local_ip, key)
        proc = _run(args+['id -u'], timeout=15)
        ok = proc.returncode == 0 and proc.stdout.strip() == '0'
        if not ok:
            self._verified_login = None
            raise BackendError('Login root non verificato. '+proc.stderr.strip())
        self._verified_login = (validate_ip(hu_ip), validate_ip(local_ip), str(validate_key(key)), time.monotonic())
        self.log('Login root confermato: id -u = 0. Nessuna modifica applicativa.')
        return True

    def _stream(self, argv, *, env_overrides=None):
        env = os.environ.copy()
        # Only the one parent launch may hand off a reserved flash attempt.
        env.pop(FLASH_ATTEMPT_ENV, None)
        if env_overrides:
            env.update(env_overrides)
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUNBUFFERED'] = '1'
        captured = []
        with subprocess.Popen([str(a) for a in argv], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, encoding='utf-8', errors='replace', bufsize=1,
                              creationflags=CREATE_NO_WINDOW, shell=False, env=env) as proc:
            for line in proc.stdout:
                line = line.rstrip('\r\n')
                captured.append(line)
                self.log(line)
            code = proc.wait()
        return code, '\n'.join(captured)

    def install(self, hu_ip, local_ip, key, include_uplink=True):
        self._write_guard()
        self.verify_files()
        expected = dict(self.last_scan or {})
        if not expected or expected.get('hu_ip') != validate_ip(hu_ip) or expected.get('local_ip') != validate_ip(local_ip):
            raise BackendError('Ripetere la lettura HU prima di installare lo Store.')
        fresh = self.scan(local_ip)
        if not fresh.get('supported') or not fresh.get('cafd_ok') or any(
                fresh.get(field) != expected.get(field) for field in ('vin', 'gateway', 'hu_ip', 'local_ip')):
            raise BackendError('La vettura o il coding sono cambiati: installazione bloccata. Ripetere i controlli.')
        self.verify_ssh(hu_ip, local_ip, key)
        machine = os.environ.get('PROCESSOR_ARCHITEW6432') or os.environ.get('PROCESSOR_ARCHITECTURE', '')
        if machine.upper() != 'AMD64':
            raise BackendError('Questa build è per Windows x64; installazione non avviata su questa architettura.')
        packed = self.resource_dir/'installer/mgu-install-windows-x64.exe.gz'
        sums = (self.resource_dir/'installer/SHA256SUMS').read_text(encoding='utf-8')
        expected = None
        for line in sums.splitlines():
            p = line.split()
            if len(p) == 2 and p[1].lstrip('*') == packed.name:
                expected = p[0].lower()
        if expected != _sha(packed):
            raise BackendError('SHA256SUMS upstream non corrisponde all’installer.')
        self.state_dir.mkdir(parents=True, exist_ok=True)
        target = self.state_dir/'mgu-install.exe'
        with gzip.open(packed, 'rb') as src, target.open('wb') as dest:
            shutil.copyfileobj(src, dest)
        kh = str(self.known_hosts).replace('\\', '/')
        args = [str(target), 'first-install', '--from', str(self.resource_dir/'payload'), '--identity', str(validate_key(key)),
                '--host', validate_ip(hu_ip), '--port', '22', '--no-restart-prompt']
        for opt in (f'BindAddress={validate_ip(local_ip)}', 'StrictHostKeyChecking=yes', f'UserKnownHostsFile="{kh}"',
                    f'GlobalKnownHostsFile="{kh}"', 'BatchMode=yes', 'IdentitiesOnly=yes', 'PasswordAuthentication=no',
                    'KbdInteractiveAuthentication=no', 'UpdateHostKeys=no', 'ConnectTimeout=10', 'ProxyCommand=none', 'ProxyJump=none'):
            args += ['--ssh-opt', opt]
        if not include_uplink:
            args.append('--no-uplink')
        code, output = self._stream(args)
        if code:
            raise BackendError(f'Installer terminato con errore {code}. Conservare il log; nessun reflash automatico.')
        self.log('Installer terminato senza errori. Verificare lo Store; il riavvio finale è un pulsante separato.')

    def reboot(self, hu_ip, local_ip, key):
        self._write_guard()
        self.verify_ssh(hu_ip, local_ip, key)
        command = ("L=/var/opt/mgu-deploy/lock; if [ -e $L ] && [ $(cut -d ' ' -f 2 $L) = $(cat /proc/sys/kernel/random/boot_id) ] && "
                   "kill -0 $(cut -d ' ' -f 1 $L) 2>/dev/null; then exit 3; fi; /usr/bin/nsm_control --requestRestart 7 --normal 2>&1")
        proc = _run(self._ssh_args(hu_ip, local_ip, key)+[command], timeout=20)
        if proc.returncode or '[Error.' in proc.stdout:
            raise BackendError('Riavvio non confermato. '+(proc.stdout+proc.stderr).strip())
        self._verified_login = None
        self.log('Richiesta di riavvio HU accettata. Attendere il ritorno di iDrive e ripetere i controlli.')

    def recover_key(self, vin):
        if self.demo:
            raise BackendError('Recupero della chiave disabilitato in demo.')
        vin = validate_vin(vin)
        self.verify_files()
        from cryptography.hazmat.primitives import serialization
        original = self.resource_dir/'vendor/root/data/assets/05_SSH_ROOT_KEY.pem'
        private = serialization.load_pem_private_key(original.read_bytes(), password=None)
        data = private.private_bytes(serialization.Encoding.PEM,
                                     serialization.PrivateFormat.OpenSSH,
                                     serialization.NoEncryption())
        target = self.state_dir/'recovered-bootstrap'/vin/'id_rsa'
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = serialization.load_ssh_private_key(target.read_bytes(), password=None)
            if existing.public_key().public_numbers() != private.public_key().public_numbers():
                raise BackendError('Nel percorso esiste una chiave diversa: non viene sovrascritta.')
        else:
            with target.open('xb') as stream:
                stream.write(data)
        _secure_key_file(target)
        self.log('Chiave bootstrap originale recuperata solo sul PC. È condivisa dal progetto; il login va ancora verificato.')
        return {'key': str(target)}

    def persist(self, vin, gateway, hu_ip, local_ip, key):
        self._write_guard()
        self.verify_files()
        vin, gateway, hu_ip, local_ip = validate_vin(vin), validate_ip(gateway), validate_ip(hu_ip), validate_ip(local_ip)
        _check_persist_target(self.scan(local_ip), vin, gateway, hu_ip)
        self.verify_ssh(hu_ip, local_ip, key)
        launch = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).with_name('main.py'))]
        launch += ['--worker', 'persist', '--state-dir', str(self.state_dir), '--resource-dir', str(self.resource_dir),
                   '--vin', vin, '--gateway', gateway, '--hu-ip', hu_ip, '--local-ip', local_ip, '--key', str(validate_key(key))]
        code, output = self._stream(launch)
        if code or 'DONE: SSH runs with debug mode OFF' not in output or 'Close routine result: confirmed' not in output:
            raise BackendError('Persistenza non confermata. Conservare il log: non viene eseguito alcun reflash o enrollment automatico.')
        self.verify_ssh(hu_ip, local_ip, key)
        self.log('Persistenza completata e login root ricontrollato. Nessun nuovo flash eseguito.')
        return True

    def flash(self, vin, gateway, hu_ip, local_ip):
        self._write_guard()
        vin, gateway, hu_ip, local_ip = validate_vin(vin), validate_ip(gateway), validate_ip(hu_ip), validate_ip(local_ip)
        if self.has_flash_attempt(vin):
            raise BackendError('Tentativo precedente rilevato per questa vettura: nuovo flash bloccato. Verificare l’esito e seguire il recupero; riavviare l’app non rimuove il blocco.')
        self.verify_files()
        fresh = self.scan(local_ip)
        _check_flash_target(fresh, vin, gateway, hu_ip)
        launch = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).with_name('main.py'))]
        launch += ['--worker', 'flash', '--state-dir', str(self.state_dir), '--resource-dir', str(self.resource_dir),
                   '--vin', vin, '--gateway', gateway, '--hu-ip', hu_ip, '--local-ip', local_ip]
        attempt_id = self._begin_flash_attempt(fresh)
        # The pre-write scan/login can no longer authorize any subsequent action.
        self.last_scan = None
        self._verified_login = None
        try:
            code, output = self._stream(launch, env_overrides={FLASH_ATTEMPT_ENV: attempt_id})
            if code or 'SSH OK as root:' not in output or 'DONE: SSH runs with debug mode OFF' not in output:
                raise BackendError(f'Sblocco non confermato (codice {code}). Conservare il log e verificare in quale fase si è fermato. Il tentativo resta registrato e un nuovo flash è bloccato. Questo errore da solo non prova che il coding sia stato modificato: non ripristinarlo alla cieca.')
            key = self.state_dir/'data/enrollments'/vin/'id_rsa'
            validate_key(key)
        except BaseException:
            self._note_flash_result(vin, attempt_id, 'needs_review')
            raise
        self._note_flash_result(vin, attempt_id, 'confirmed')
        self.log('Sblocco confermato dai log. Ora ripristinare/verificare il coding in BimmerCode prima dello Store.')
        return {'key': str(key), 'vin': vin, 'log_dir': str(self.state_dir/'logs')}


def _check_flash_target(scan, vin, gateway, hu_ip):
    if not scan.get('supported') or not scan.get('cafd_ok'):
        raise BackendError('HU non supportata o CAFD non valido: flash bloccato.')
    if any(scan.get(k) != v for k, v in (('vin', vin), ('gateway', gateway), ('hu_ip', hu_ip))):
        raise BackendError('I dati della vettura sono cambiati dall’ultima lettura: flash bloccato.')
    # An already open SSH service must be investigated, never reflexively reflashed.
    if scan.get('ssh_open'):
        raise BackendError('SSH è già aperto. Verificare la chiave e il login; non viene avviato un nuovo flash.')


def _check_persist_target(scan, vin, gateway, hu_ip):
    if not scan.get('supported') or not scan.get('cafd_ok') or not scan.get('ssh_open'):
        raise BackendError('Persistenza bloccata: servono HU riconosciuta, coding valido e SSH già aperto.')
    if any(scan.get(k) != v for k, v in (('vin', vin), ('gateway', gateway), ('hu_ip', hu_ip))):
        raise BackendError('Identità della vettura cambiata: persistenza bloccata.')


def _readback_with_busy_retry(readback, reject_type, log):
    """Retry only the pinned enrollment readback, never enrollment or flashing.

    Upstream wraps UdsReject in EnrollError; inspect the typed original context,
    not an error message that might misclassify a different request or failure.
    """
    def retry(client, *args, **kwargs):
        for attempt in range(1, 6):
            try:
                return readback(client, *args, **kwargs)
            except Exception as exc:
                reject = exc if isinstance(exc, reject_type) else (exc.__cause__ or exc.__context__)
                if not isinstance(reject, reject_type) or reject.sid != 0x22 or reject.nrc != 0x21 or attempt == 5:
                    raise
                log(f'HU occupata al readback 22 17 2A: ripetizione della sola lettura {attempt+1}/5 tra 1 secondo.')
                time.sleep(1)
    return retry


def _strict_persist_verification(run_persist, diag):
    """Require an explicit negative debug DTC reading before upstream says DONE.

    The pinned implementation accepts an unknown diagnostic state. Limit this
    runtime override to run_persist's final check, leaving discovery/status alone.
    """
    def strict(tool):
        read_state = diag.debug_state
        def checked_state(*args, **kwargs):
            state = read_state(*args, **kwargs)
            if not isinstance(state, dict) or state.get('dtc_debug') is not False:
                raise BackendError('SSH potrebbe essere già persistente, ma debug OFF non è confermato da una lettura diagnostica valida. Esito da verificare: nessun nuovo flash o ripristino automatico.')
            return state
        diag.debug_state = checked_state
        try:
            return run_persist(tool)
        finally:
            diag.debug_state = read_state
    return strict


def run_root_worker(args, state_dir, resource_dir):
    """Called only by main.py's worker branch; never invoked during GUI import."""
    def val(name):
        return args.get(name) if isinstance(args, dict) else getattr(args, name)
    vin, gateway = validate_vin(val('vin')), validate_ip(val('gateway'))
    hu_ip, local_ip = validate_ip(val('hu_ip')), validate_ip(val('local_ip'))
    action = val('worker')
    if action not in ('flash', 'persist'):
        raise BackendError('Azione worker non consentita.')
    backend = Backend(resource_dir, state_dir, lambda text: print(text, flush=True))
    backend._write_guard()
    backend.verify_files()
    fresh = backend.scan(local_ip)
    if action == 'persist':
        _check_persist_target(fresh, vin, gateway, hu_ip)
        selected_key = validate_key(val('key'))
        backend.verify_ssh(hu_ip, local_ip, selected_key)
    else:
        _check_flash_target(fresh, vin, gateway, hu_ip)
        attempt_id = backend._claim_flash_attempt(fresh, os.environ.get(FLASH_ATTEMPT_ENV))
    discovery, hsfz, diag = backend._load_upstream()
    ssh_enable = importlib.import_module('ssh_enable')
    assets = importlib.import_module('mgu7.assets')
    identity = importlib.import_module('mgu7.identity')
    enroll = importlib.import_module('mgu7.enroll')
    if action == 'flash':
        enroll.readback_certificate_address = _readback_with_busy_retry(
            enroll.readback_certificate_address, hsfz.UdsReject, backend.log)
    sshcli = importlib.import_module('mgu7.sshcli')
    ssh_enable.Tool.run_persist = _strict_persist_verification(ssh_enable.Tool.run_persist, diag)
    sshcli.ssh_binary = lambda: _binary('ssh')
    def ssh_available():
        try:
            _binary('ssh')
            return True
        except BackendError:
            return False
    sshcli.available = ssh_available
    sshcli.secure_key_file = _secure_key_file
    vendor = Path(resource_dir)/'vendor/root'
    ssh_enable.HERE = str(vendor)
    assets.Assets.__init__.__defaults__ = (str(vendor/'data/assets'),)
    identity.HERE = str(state_dir)
    identity.ENROLL_DIR = str(Path(state_dir)/'data/enrollments')
    logs = Path(state_dir)/'logs'
    logs.mkdir(parents=True, exist_ok=True)

    def bound_connect(self):
        self.close()
        self.sock = socket.create_connection((self.gateway, self.port), timeout=10, source_address=(local_ip, 0))
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(30)
        self.buf = b''
    hsfz.EnetClient.connect = bound_connect
    if action == 'persist':
        original_request = hsfz.EnetClient.request
        def persist_request(self, dst, request, profile):
            allowed = (b'\x22\xf1\x01', b'\x22\x17\x2a', b'\x19\x02\x0c', b'\x31\x02\xa0\xfd')
            if dst != hsfz.MGU or request not in allowed:
                raise BackendError('Comando diagnostico fuori dalla procedura di persistenza: bloccato.')
            return original_request(self, dst, request, profile)
        hsfz.EnetClient.request = persist_request
        ssh_enable.Tool._load_identity = lambda self: str(selected_key)
        # A recovery of existing SSH must never fall back to an ECU reset.
        ssh_enable.Tool.wake_daemon = lambda self, host: False
    def bound_probe(host, port=22, timeout=3.0):
        start = time.monotonic()
        ok = backend._port(validate_ip(host), local_ip, timeout)
        return ok, (time.monotonic()-start)*1000
    enroll.probe_port = bound_probe
    original_base = sshcli._base_argv
    def bound_ssh(*a, **kw):
        if action == 'persist':
            if a[0] != hu_ip or (len(a) > 2 and a[2] != 'root') or (len(a) > 3 and int(a[3]) != 22):
                raise BackendError('Destinazione SSH non consentita.')
            return backend._ssh_args(hu_ip, local_ip, a[1])
        argv = original_base(*a, **kw)
        return argv[:1]+['-b', local_ip]+argv[1:]
    sshcli._base_argv = bound_ssh
    class HiddenSubprocess:
        def __getattr__(self, name):
            return getattr(subprocess, name)
        def run(self, *a, **kw):
            kw.setdefault('creationflags', CREATE_NO_WINDOW)
            return subprocess.run(*a, **kw)
    sshcli.subprocess = HiddenSubprocess()
    logfile = logs/('root-'+action+'-'+time.strftime('%Y%m%d-%H%M%S')+'.log')
    # No force, fix-key, unique-key, or keep-debug: this is the pinned upstream ID7 path.
    try:
        result = ssh_enable.main([action, '--gateway', gateway, '--vin', vin, '--arch', 'id7',
                                 '--mgu-ip', hu_ip, '--persist', '--no-unique-key', '--yes', '--log', str(logfile)])
    except BaseException:
        if action == 'flash':
            backend._note_flash_result(vin, attempt_id, 'needs_review')
        raise
    if action == 'flash':
        backend._note_flash_result(vin, attempt_id, 'worker_finished' if not result else 'needs_review', exit_code=result)
    return result
