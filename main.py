"""MGU Assistant: guided, local Windows UI for the owner's BMW MGU.

No network or vehicle operation occurs on startup. Every action runs through
the backend, one at a time. Confirmation state exists for this session only.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from backend import Backend, run_root_worker

APP_NAME = "MGU Assistant"
VERSION = "0.2.0-beta.1"
BG = "#f2f5fa"
NAVY = "#132139"
BLUE = "#1d5ed8"
INK = "#17283f"
MUTED = "#56677c"


def app_folder() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def _restore_worker_streams() -> None:
    """Configure UTF-8 explicitly, including PyInstaller's existing pipe streams.

    Frozen Python can ignore PYTHONIOENCODING. A cp1252 stdout otherwise fails
    on the upstream progress arrow before the first flash frame. Configure
    both pipes before any upstream operation; tolerate unpaired surrogates.
    Missing windowed streams are recovered without allocating a console.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)
    if os.name != "nt":
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                      ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                      wintypes.BOOL, wintypes.DWORD]
    kernel.DuplicateHandle.restype = wintypes.BOOL
    process = kernel.GetCurrentProcess()
    for name, standard in (("stdout", -11), ("stderr", -12)):
        if getattr(sys, name) is not None:
            continue
        handle = kernel.GetStdHandle(standard & 0xffffffff)
        duplicate = wintypes.HANDLE()
        if handle and handle != wintypes.HANDLE(-1).value and kernel.DuplicateHandle(
                process, handle, process, ctypes.byref(duplicate), 0, False, 2):
            descriptor = msvcrt.open_osfhandle(duplicate.value, os.O_WRONLY | os.O_BINARY)
            setattr(sys, name, os.fdopen(descriptor, "w", encoding="utf-8", errors="backslashreplace", buffering=1))
        else:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="backslashreplace"))


class MGUApp:
    STAGES = [
        ("1", "Connessione", "Controlla PC, ENET e centralina"),
        ("2", "Backup e sblocco", "Prepara i prerequisiti dello sblocco"),
        ("3", "Chiave e coding", "Verifica accesso root e ripristino"),
        ("4", "Installa Store", "Installa i componenti offline"),
        ("5", "Riavvio e verifica", "Completa e controlla le funzioni"),
    ]

    def __init__(self, root: tk.Tk, resource_dir: Path, state_dir: Path, demo: bool = False):
        self.root = root
        self.resource_dir = resource_dir.resolve()
        self.state_dir = state_dir.resolve()
        self.demo = demo
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "logs").mkdir(exist_ok=True)
        self.log_path = self.state_dir / "logs" / ("session-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".log")
        self.log_file = self.log_path.open("a", encoding="utf-8", buffering=1)
        self.log_error = False
        self.events = queue.Queue()
        self.backend = Backend(self.resource_dir, self.state_dir, self.thread_log, demo=demo)
        self.busy = False
        self.write_busy = False
        self.closed = False
        self.pc_checked = False
        self.scan_result = None
        self.scan_time = 0.0
        self.host_accepted = None
        self.ssh_verified = None
        self.files_verified = False
        self.install_success = False
        self.flash_success = False
        self.known_root_vins = set()
        self.adapters = {}
        self.current_stage = 0
        self.controls = []
        self.nav_buttons = []
        self.pages = []
        self.actions = {}
        self.key = tk.StringVar()
        self.adapter = tk.StringVar()
        self.backup = tk.StringVar()
        self.backup_ok = tk.BooleanVar()
        self.hu_ok = tk.BooleanVar()
        self.power_ok = tk.BooleanVar()
        self.physical_key = tk.BooleanVar()
        self.coding_ok = tk.BooleanVar()
        self.uplink = tk.BooleanVar(value=True)
        self.final_checks = [tk.BooleanVar() for _ in range(4)]
        self.pc_text = tk.StringVar(value="Non controllato. Nessuna connessione viene avviata automaticamente.")
        self.hu_text = tk.StringVar(value="Collega ENET e scegli la scheda Ethernet, poi premi Leggi la HU.")
        self.root_text = tk.StringVar(value="Accesso root non verificato")
        self.store_text = tk.StringVar(value="File non ancora verificati · installazione non eseguita")
        self.backup_text = tk.StringVar(value="Nessun backup selezionato")
        self.status = tk.StringVar(value="Pronto · nessuna operazione sulla vettura")
        self.stage_title = tk.StringVar()
        self.stage_subtitle = tk.StringVar()
        self._build()
        self.key.trace_add("write", self._key_changed)
        self.adapter.trace_add("write", self._adapter_changed)
        self.backup.trace_add("write", self._prerequisite_changed)
        for variable in (self.backup_ok, self.hu_ok, self.power_ok, self.physical_key, self.coding_ok):
            variable.trace_add("write", self._prerequisite_changed)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(70, self._poll)
        self.show_stage(0)
        self._log("MGU Assistant " + VERSION + (" — MODALITÀ DEMO: nessuna operazione sulla vettura." if demo else " — nessuna operazione avviata."))
        self._log("Log locali: possono contenere VIN, IP e percorsi. Esaminali prima di condividerli. Non includono intenzionalmente il contenuto delle chiavi.")
        self._refresh()

    def _build(self):
        self.root.title(APP_NAME + " — BMW MGU / iDrive 7" + (" — DEMO" if self.demo else ""))
        self.root.geometry("1240x900")
        self.root.minsize(1080, 760)
        self.root.configure(bg=BG)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("Body.TLabel", background="white", foreground=INK, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background="white", foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Card.TFrame", background="white")
        style.configure("Card.TLabelframe", background="white", bordercolor="#dbe3ed", relief="solid")
        style.configure("Card.TLabelframe.Label", background="white", foreground=INK, font=("Segoe UI Semibold", 11))
        style.configure("TButton", font=("Segoe UI", 10), padding=(13, 8), background="#e7edf5", foreground=INK, borderwidth=0)
        style.map("TButton", background=[("active", "#d9e5f4"), ("disabled", "#eef1f5")], foreground=[("disabled", "#8794a5")])
        style.configure("Accent.TButton", background=BLUE, foreground="white", font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", "#174cae"), ("disabled", "#dce4f2")], foreground=[("disabled", "#8794a5")])
        style.configure("Danger.TButton", background="#a93a32", foreground="white", font=("Segoe UI Semibold", 10))
        style.map("Danger.TButton", background=[("active", "#8e2a23"), ("disabled", "#eadedc")], foreground=[("disabled", "#998783")])
        style.configure("TCheckbutton", background="white", foreground=INK, font=("Segoe UI", 10), padding=(0, 5))
        style.map("TCheckbutton", background=[("active", "white")])
        style.configure("TEntry", padding=7, font=("Segoe UI", 10))
        style.configure("TCombobox", padding=7, font=("Segoe UI", 10))
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=25, borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9), background="#e9eff7")

        sidebar = tk.Frame(self.root, bg=NAVY, width=242)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="MGU", bg=NAVY, fg="white", font=("Segoe UI", 28, "bold"), anchor="w").pack(fill="x", padx=24, pady=(25, 0))
        tk.Label(sidebar, text="ASSISTANT", bg=NAVY, fg="#7faeff", font=("Segoe UI", 12, "bold"), anchor="w").pack(fill="x", padx=25)
        tk.Label(sidebar, text="BMW MGU  •  iDrive 7", bg=NAVY, fg="#b3c3d9", font=("Segoe UI", 10), anchor="w").pack(fill="x", padx=25, pady=(8, 26))
        for i, (number, title, subtitle) in enumerate(self.STAGES):
            button = tk.Button(sidebar, text=number + "  " + title, anchor="w", padx=16, pady=13,
                               bg=NAVY, fg="#d6e1ef", activebackground="#243e65", activeforeground="white",
                               bd=0, relief="flat", font=("Segoe UI Semibold", 10), cursor="hand2",
                               command=lambda index=i: self.show_stage(index))
            button.pack(fill="x", padx=11, pady=3)
            self.nav_buttons.append(button)
        lower = tk.Frame(sidebar, bg=NAVY)
        lower.pack(side="bottom", fill="x", padx=24, pady=23)
        if self.demo:
            tk.Label(lower, text="DEMO · SCRITTURE BLOCCATE", bg="#72531f", fg="#fff0bd", font=("Segoe UI", 9, "bold"), padx=7, pady=8).pack(fill="x", pady=(0, 12))
        tk.Label(lower, text="Strumento indipendente\nNon certificato BMW\nVersione " + VERSION,
                 bg=NAVY, fg="#aabbd2", justify="left", font=("Segoe UI", 9)).pack(anchor="w")

        right = ttk.Frame(self.root, padding=(24, 18, 24, 12))
        right.pack(fill="both", expand=True)
        top = ttk.Frame(right)
        top.pack(fill="x", pady=(0, 13))
        title_area = ttk.Frame(top)
        title_area.pack(side="left", fill="x", expand=True)
        ttk.Label(title_area, textvariable=self.stage_title, font=("Segoe UI Semibold", 22)).pack(anchor="w")
        ttk.Label(title_area, textvariable=self.stage_subtitle, foreground=MUTED).pack(anchor="w", pady=(4, 0))
        ttk.Button(top, text="Apri guida", command=self.open_guide).pack(side="right", padx=(8, 0))
        ttk.Button(top, text="Apri log", command=self.open_log).pack(side="right")

        panels = ttk.Panedwindow(right, orient="vertical")
        panels.pack(fill="both", expand=True)
        content = ttk.Frame(panels)
        panels.add(content, weight=4)
        self.canvas = tk.Canvas(content, bg=BG, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(content, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.page_host = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.page_host, anchor="nw")
        self.page_host.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.canvas_window, width=event.width))
        self.canvas.bind_all("<MouseWheel>", self._wheel, add=True)
        for builder in (self._connection_page, self._root_page, self._key_page, self._store_page, self._finish_page):
            page = ttk.Frame(self.page_host)
            self.pages.append(page)
            builder(page)

        logs = ttk.Frame(panels, padding=(0, 13, 0, 0))
        panels.add(logs, weight=1)
        log_head = ttk.Frame(logs)
        log_head.pack(fill="x", pady=(0, 6))
        ttk.Label(log_head, text="Registro attività", font=("Segoe UI Semibold", 11)).pack(side="left")
        ttk.Button(log_head, text="Copia", command=self.copy_log).pack(side="right", padx=(7, 0))
        ttk.Button(log_head, text="Esporta…", command=self.export_log).pack(side="right")
        self.log_widget = tk.Text(logs, height=9, bg="#101d30", fg="#d9e5f5", insertbackground="white",
                                  font=("Consolas", 9), wrap="word", relief="flat", padx=12, pady=9, state="disabled")
        self.log_widget.pack(fill="both", expand=True)
        self.progress = ttk.Progressbar(right, mode="indeterminate")
        self.progress.pack(fill="x", pady=(11, 6))
        ttk.Label(right, textvariable=self.status, foreground=MUTED, font=("Segoe UI", 9)).pack(anchor="w")

    def _wheel(self, event):
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        if widget and (widget == self.canvas or str(widget).startswith(str(self.page_host))):
            self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def card(self, parent, title):
        frame = ttk.LabelFrame(parent, text=title, style="Card.TLabelframe", padding=17)
        frame.pack(fill="x", padx=(0, 5), pady=(0, 14))
        return frame

    def text(self, parent, value, muted=False):
        label = ttk.Label(parent, text=value, style="Muted.TLabel" if muted else "Body.TLabel", wraplength=820, justify="left")
        label.pack(anchor="w", fill="x", pady=(0, 8))
        return label

    def button(self, parent, name, title, command, style="TButton", side="left"):
        control = ttk.Button(parent, text=title, command=command, style=style)
        control.pack(side=side, padx=(0, 8), pady=(5, 0))
        self.controls.append((control, "normal"))
        self.actions[name] = control
        return control

    def check(self, parent, variable, title):
        control = ttk.Checkbutton(parent, text=title, variable=variable)
        control.pack(anchor="w", fill="x")
        self.controls.append((control, "normal"))
        return control

    def _connection_page(self, page):
        card = self.card(page, "Collega il PC alla vettura")
        self.text(card, "Auto ferma, quadro acceso. Collega il cavo ENET alla porta OBD e all'Ethernet del PC. Il controllo iniziale legge soltanto i dati: non abilita SSH e non esegue flash.")
        ttk.Label(card, textvariable=self.pc_text, style="Muted.TLabel", wraplength=800).pack(anchor="w", pady=(0, 9))
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "pc", "Controlla PC e schede", self.check_pc, "Accent.TButton")
        card = self.card(page, "Scheda Ethernet ENET")
        self.text(card, "Scegli la scheda collegata all'auto. Sono elencati gli indirizzi locali 169.254.x.x. Wi-Fi e Internet non vengono modificati.", True)
        self.adapter_combo = ttk.Combobox(card, textvariable=self.adapter, state="readonly", width=70)
        self.adapter_combo.pack(fill="x", pady=(0, 8))
        self.controls.append((self.adapter_combo, "readonly"))
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "scan", "Leggi la HU", self.scan, "Accent.TButton")
        card = self.card(page, "Identificazione della centralina")
        ttk.Label(card, textvariable=self.hu_text, style="Body.TLabel", wraplength=800, justify="left").pack(anchor="w", fill="x", pady=(0, 11))
        self.svk_table = ttk.Treeview(card, columns=("type", "id", "version"), show="headings", height=4)
        for name, label, width in (("type", "Componente", 130), ("id", "Identificativo", 210), ("version", "Versione", 210)):
            self.svk_table.heading(name, text=label); self.svk_table.column(name, width=width, stretch=True)
        self.svk_table.pack(fill="x")
        self.text(card, "Il filtro del progetto non certifica ogni firmware. VIN diverso, HU non riconosciuta o CAFD assente richiedono di fermarsi.", True)

    def _root_page(self, page):
        card = self.card(page, "Backup coding: passaggio manuale con BimmerCode")
        self.text(card, "Usa BimmerCode per leggere HU_MGU ed esportare un backup valido PRIMA dello sblocco. Questa app non crea né ripristina backup BimmerCode e non può certificarne il contenuto.")
        ttk.Label(card, textvariable=self.backup_text, style="Muted.TLabel", wraplength=800).pack(anchor="w", fill="x")
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "backup_file", "Seleziona file backup…", self.pick_backup)
        self.button(row, "backup_folder", "Seleziona cartella…", lambda: self.pick_backup(folder=True))
        card = self.card(page, "Prima di modificare la HU")
        self.check(card, self.backup_ok, "Ho un backup precedente esportato e una procedura di ripristino utilizzabile.")
        self.check(card, self.hu_ok, "Ho verificato HU_MGU, iDrive 7 e la versione software della mia vettura.")
        self.check(card, self.power_ok, "Auto ferma e alimentazione stabilizzata adeguata; PC alimentato, senza sospensione.")
        self.check(card, self.physical_key, "Ho la chiave fisica. Il backup coding non salva le associazioni Digital Key.")
        card = self.card(page, "Sblocco iniziale: Flash + Enable")
        self.text(card, "Riprogramma la HU e abilita SSH con la procedura originale del progetto. Può cancellare coding/CAFD e Digital Key o rendere inutilizzabile la centralina. Se root funziona già, salta questo passaggio.")
        self.text(card, "La procedura usa ID7, lascia la chiave univoca avanzata disattivata e richiede debug spento a fine operazione. Non sono disponibili forzature, Fix key o riparazioni automatiche.", True)
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "flash", "Flash + Enable…", self.flash, "Danger.TButton")
        self.flash_hint = ttk.Label(card, text="", style="Muted.TLabel", wraplength=800)
        self.flash_hint.pack(anchor="w", fill="x", pady=(11, 0))

    def _key_page(self, page):
        card = self.card(page, "Chiave privata root")
        self.text(card, "Scegli id_rsa senza estensione, non id_rsa.pub o .ppk. Dopo uno sblocco riuscito, l'app seleziona il percorso restituito dal progetto. Non inviare il contenuto della chiave in chat.")
        entry = ttk.Entry(card, textvariable=self.key)
        entry.pack(fill="x", pady=(0, 7)); self.controls.append((entry, "normal"))
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "key", "Seleziona id_rsa…", self.pick_key)
        self.button(row, "recover_key", "Recupera chiave originale sul PC", self.recover_key)
        self.text(card, "Se il flash è terminato ma l'app si è fermata prima di esportare la chiave, puoi recuperare la chiave bootstrap già inclusa nel progetto. Non modifica la vettura e non garantisce che il login riesca.", True)
        card = self.card(page, "Identità della HU e prova root")
        self.text(card, "Prima acquisisci e conferma la chiave del SERVER HU sul collegamento ENET diretto. Questa impronta è diversa da quella della tua chiave privata elencata in connect.txt. Senza un riferimento precedente, è una scelta di fiducia iniziale.")
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "fingerprint", "Leggi impronta HU…", self.read_fingerprint)
        self.button(row, "ssh", "Verifica accesso root", self.verify_ssh, "Accent.TButton")
        ttk.Label(card, textvariable=self.root_text, style="Body.TLabel", wraplength=800).pack(anchor="w", pady=(12, 0))
        card = self.card(page, "Ripristino coding e controllo funzioni")
        self.text(card, "Se hai effettuato il flash: dopo la sua conclusione, chiudi le connessioni diagnostiche e ripristina in BimmerCode il backup PRECEDENTE. Poi ricollega ENET al PC. Se una funzione rimane assente, risolvi il coding prima dello Store.")
        self.check(card, self.coding_ok, "Ho ripristinato il coding se necessario e verificato le funzioni originali della HU.")
        card = self.card(page, "Completa SSH già aperto — senza nuovo flash")
        self.text(card, "Dopo un'interruzione successiva al flash: prima verifica il login root e il coding. Questo pulsante installa la persistenza SSH e disattiva il debug tramite la procedura originale. Modifica servizi sulla HU; non esegue flash, enrollment o riavvii automatici.")
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "persist", "Completa persistenza SSH…", self.persist, "Accent.TButton")

    def _store_page(self, page):
        card = self.card(page, "Componenti locali, verificati prima dell'uso")
        self.text(card, "L'installer ufficiale usa i componenti inclusi nel pacchetto. Non serve Internet per la prima installazione. Gli aggiornamenti e le app aggiuntive possono richiederlo. Il controllo SHA256 rileva modifiche, non certifica la compatibilità BMW.")
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "files", "Verifica file del pacchetto", self.verify_files)
        ttk.Label(card, textvariable=self.store_text, style="Body.TLabel", wraplength=800).pack(anchor="w", fill="x", pady=(12, 0))
        card = self.card(page, "Prima installazione dello Store")
        self.text(card, "Installa Store, deploy, updater, app-privacy, Python sulla HU e renderer. Scrive file e modifica servizi della centralina. L'installer non avvia lo sblocco root. Il riavvio finale è un'azione separata.")
        self.check(card, self.uplink, "Includi Internet uplink (configurazione completa del progetto)")
        self.text(card, "App-privacy interviene sui report applicativi: non garantisce invisibilità o conservazione della garanzia. Il Wi-Fi/Internet dello Store andrà configurato sulla HU.", True)
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "install", "Installa MGU Store…", self.install, "Accent.TButton")
        self.install_hint = ttk.Label(card, text="", style="Muted.TLabel", wraplength=800)
        self.install_hint.pack(anchor="w", fill="x", pady=(11, 0))

    def _finish_page(self, page):
        card = self.card(page, "Riavvio della head unit")
        self.text(card, "Dopo un'installazione riuscita, riavvia la HU a vettura ferma per completare l'attivazione. Non spegnere la vettura né scollegare l'alimentazione mentre un'operazione è in corso.")
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "reboot", "Riavvia la HU…", self.reboot, "Accent.TButton")
        card = self.card(page, "Controlli nell'auto")
        for var, text in zip(self.final_checks, (
                "MGU Store compare tra le app e si apre.",
                "Audio, lingua, menu e impostazioni originali sono regolari.",
                "Ho controllato in sicurezza telecamera e altre funzioni originali.",
                "Ho conservato backup coding, chiavi e log in un luogo protetto.")):
            self.check(card, var, text)
        self.text(card, "Per Internet: nello Store usa Settings → Wi-Fi e l'hotspot del telefono, poi verifica Online. Il PC online non rende automaticamente online la HU. Installa soltanto app compatibili ID7, una alla volta.", True)
        self.text(card, "Se qualcosa non funziona: conserva il log, non riflashare e non applicare riparazioni automatiche. I controlli spuntati sono dichiarazioni dell'utente, non test automatici.", True)

    def show_stage(self, index):
        for page in self.pages:
            page.pack_forget()
        self.current_stage = index
        self.pages[index].pack(fill="both", expand=True)
        number, title, subtitle = self.STAGES[index]
        self.stage_title.set(title)
        self.stage_subtitle.set("PASSAGGIO " + number + " DI 5  ·  " + subtitle)
        for i, button in enumerate(self.nav_buttons):
            button.configure(bg="#263f65" if i == index else NAVY, fg="white" if i == index else "#d6e1ef")
        self.canvas.yview_moveto(0)

    def _local_ip(self):
        selected = self.adapters.get(self.adapter.get())
        return selected["ip"] if selected else ""

    def _identity(self):
        if not self.scan_result:
            return None
        return (self.scan_result.get("vin"), self.scan_result.get("gateway"), self.scan_result.get("hu_ip"), self._local_ip(), self.key.get().strip())

    def _root_ready(self):
        return bool(self.ssh_verified and self.ssh_verified == self._identity())

    def _root_seen(self):
        return bool(self.scan_result and self.scan_result.get("vin") in self.known_root_vins)

    def _flash_attempted(self):
        vin = (self.scan_result or {}).get("vin")
        return bool(vin and self.backend.has_flash_attempt(vin))

    def _backup_present(self):
        return bool(self.backup.get() and Path(self.backup.get()).exists())

    def _scan_ready(self):
        s = self.scan_result or {}
        return bool(s.get("supported") and s.get("cafd_ok") and s.get("vin") and s.get("hu_ip") and self._local_ip())

    def _prerequisites(self):
        return not self.log_error and self._backup_present() and all(v.get() for v in (self.backup_ok, self.hu_ok, self.power_ok, self.physical_key))

    def _adapter_changed(self, *_):
        self.scan_result = None
        self.scan_time = 0
        self.host_accepted = None
        self.ssh_verified = None
        self.install_success = False
        self.flash_success = False
        self.coding_ok.set(False)
        self.hu_text.set("Scheda cambiata: ripeti la lettura della HU.")
        self.root_text.set("Accesso root non verificato")
        for item in self.svk_table.get_children():
            self.svk_table.delete(item)
        self._refresh()

    def _key_changed(self, *_):
        self.ssh_verified = None
        self.install_success = False
        self.root_text.set("Chiave cambiata: ripeti la verifica root.")
        self._refresh()

    def _prerequisite_changed(self, *_):
        self._refresh()

    def _refresh(self):
        if not hasattr(self, "flash_hint"):
            return
        for control, usual_state in self.controls:
            control.configure(state="disabled" if self.busy else usual_state)
        available = {
            "scan": self.pc_checked and bool(self._local_ip()),
            "flash": self._scan_ready() and self._prerequisites() and not (self.scan_result or {}).get('ssh_open') and not self._root_seen() and not self._flash_attempted() and not self.flash_success and not self.demo,
            "recover_key": self._scan_ready() and bool((self.scan_result or {}).get('ssh_open')) and not self.demo,
            "persist": self._scan_ready() and self._root_ready() and self._prerequisites() and self.coding_ok.get() and not self.demo,
            "fingerprint": bool(self.scan_result and self.scan_result.get("hu_ip") and self._local_ip()),
            "ssh": bool(self.scan_result and self.key.get().strip() and self.host_accepted == (self.scan_result.get("hu_ip"), self._local_ip())),
            "install": self._scan_ready() and self._root_ready() and self._prerequisites() and self.coding_ok.get() and self.files_verified and not self.demo,
            "reboot": self._root_ready() and self.install_success and self.power_ok.get() and not self.demo,
        }
        for name, enabled in available.items():
            self.actions[name].configure(state="normal" if enabled and not self.busy else "disabled")
        if self.demo:
            self.flash_hint.configure(text="Modalità demo: tutte le operazioni di scrittura sulla vettura sono bloccate.")
        elif self._flash_attempted():
            self.flash_hint.configure(text="Un tentativo di flash è già registrato per questo VIN: ripetizione bloccata anche dopo un riavvio. Consulta la guida di recupero e conserva il log.")
        elif self._root_seen() or self.flash_success or (self.scan_result or {}).get('ssh_open'):
            self.flash_hint.configure(text="Porta SSH aperta o sblocco già riuscito: non ripetere il flash. Verifica il login nella pagina Chiave e coding.")
        else:
            self.flash_hint.configure(text="Servono lettura HU valida, backup selezionato e tutte le conferme. La lettura verrà ripetuta immediatamente prima del flash.")
        self.install_hint.configure(text="Servono: HU identificata, backup e alimentazione confermati, login root verificato, coding controllato e file integri." if not self.demo else "Modalità demo: l'installazione è disabilitata.")

    def thread_log(self, line):
        self.events.put(("log", str(line)))

    def _log(self, text):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = "[" + stamp + "] " + str(text).rstrip() + "\n"
        try:
            self.log_file.write(line)
        except OSError:
            if not self.log_error:
                line += "REGISTRO NON SCRIVIBILE: conserva il testo dalla finestra. Nessuna nuova scrittura sarà avviata; quella in corso deve terminare.\n"
            self.log_error = True
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", line)
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _operation(self, title, operation, on_success=None, writes=False):
        if self.busy:
            return
        if writes and self.log_error:
            messagebox.showerror("Registro non scrivibile", "Risolvi il problema del registro prima di una nuova operazione. Conserva il testo dalla finestra.", parent=self.root)
            return
        if writes and self.demo:
            messagebox.showinfo("Demo", "Le operazioni sulla vettura sono bloccate in modalità demo.", parent=self.root)
            return
        self.busy = True
        self.write_busy = writes
        self.status.set(title + (" · non scollegare, non chiudere l'app" if writes else " · operazione in corso"))
        self.progress.start(12)
        self._refresh()
        self._log(title)
        def execute():
            try:
                result = operation()
                self.events.put(("success", (title, result, on_success)))
            except BaseException as exc:
                self.events.put(("error", (title, str(exc) or type(exc).__name__)))
        threading.Thread(target=execute, name="MGU-operation", daemon=False).start()

    def _poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._log(payload)
                else:
                    was_writing = self.write_busy
                    self.busy = False
                    self.write_busy = False
                    self.progress.stop()
                    if kind == "success":
                        title, result, callback = payload
                        self._log(title + ": completato.")
                        self.status.set("Completato · " + title)
                        if callback:
                            try:
                                callback(result)
                            except Exception as exc:
                                if was_writing:
                                    self._adapter_changed()
                                self._log("Esito non utilizzabile: " + str(exc))
                                self.status.set("Esito da verificare · consulta il registro")
                                messagebox.showerror("Esito da verificare", str(exc), parent=self.root)
                    else:
                        if was_writing:
                            self._adapter_changed()
                            self.hu_text.set("Esito della scrittura da verificare: ripeti la lettura HU. Non ripetere il flash.")
                        title, error = payload
                        self._log(title + ": ERRORE — " + error)
                        self.status.set("Operazione non riuscita · consulta il registro")
                        messagebox.showerror("Operazione non riuscita", error + "\n\nConserva il log. Nessuna riparazione o ripetizione del flash verrà avviata automaticamente.", parent=self.root)
                    self._refresh()
        except queue.Empty:
            pass
        self.root.after(70, self._poll)

    def check_pc(self):
        def done(data):
            self.pc_checked = bool(data.get("ssh"))
            self.pc_text.set("OpenSSH disponibile" if self.pc_checked else "Client OpenSSH non disponibile: installalo dalle Funzionalità facoltative Windows.")
            self.adapters = {}
            for item in data.get("adapters", []):
                label = f"{item['name']}  ·  {item['ip']}  ·  indice {item['index']}"
                self.adapters[label] = item
            self.adapter_combo.configure(values=list(self.adapters))
            self.adapter.set(next(iter(self.adapters)) if len(self.adapters) == 1 else "")
            if not self.adapters:
                self.pc_text.set(self.pc_text.get() + " · Nessuna Ethernet ENET attiva: controlla cavo, adattatore e quadro.")
        self._operation("Controllo locale del PC", self.backend.check_pc, done)

    def scan(self):
        self.ssh_verified = None
        self.host_accepted = None
        self.install_success = False
        self.coding_ok.set(False)
        self.scan_result = None
        local_ip = self._local_ip()
        def done(data):
            self.scan_result = data
            self.scan_time = time.monotonic()
            compatibility = "Filtro MGU riconosciuto" if data.get("supported") else "HU non supportata: fermarsi"
            coding = "CAFD presente" if data.get("cafd_ok") else "CAFD assente/non valido: fermarsi"
            self.hu_text.set(f"VIN: {data.get('vin', 'non disponibile')}\nGateway: {data.get('gateway', '—')}   •   HU: {data.get('hu_ip', '—')}\n{compatibility}   •   {coding}\nPorta SSH: {'aperta (non prova il login root)' if data.get('ssh_open') else 'non raggiungibile'}")
            for item in self.svk_table.get_children():
                self.svk_table.delete(item)
            for record in data.get("svk", []):
                self.svk_table.insert("", "end", values=(record.get("type"), record.get("id"), record.get("version")))
            self.root_text.set("Accesso root non verificato")
        self._operation("Lettura HU in sola lettura", lambda: self.backend.scan(local_ip), done)

    def pick_backup(self, folder=False):
        selected = filedialog.askdirectory(title="Seleziona la cartella dei backup esportati", parent=self.root) if folder else filedialog.askopenfilename(title="Seleziona un backup coding precedente al flash", parent=self.root)
        if selected:
            self.backup.set(selected)
            self.backup_ok.set(False)
            self.backup_text.set(selected + "\nPercorso registrato; validità e ripristinabilità da confermare personalmente.")

    def flash(self):
        if self.demo or not self._scan_ready() or not self._prerequisites() or self._root_seen() or self._flash_attempted() or self.flash_success or self.scan_result.get('ssh_open'):
            return
        vin = self.scan_result["vin"]
        confirmation = simpledialog.askstring("Conferma VIN prima del flash", "Il flash può cancellare coding/CAFD e Digital Key e danneggiare la HU.\n\nVIN rilevato: " + vin + "\n\nConfrontalo con la vettura e riscrivilo per proseguire:", parent=self.root)
        if confirmation is None or confirmation.strip().upper() != vin.upper():
            self._log("Flash non avviato: VIN non confermato.")
            return
        if not messagebox.askyesno("Ultima conferma: riprogrammazione HU", "Avviare davvero Flash + Enable sulla tua auto?\n\nLa lettura HU verrà ricontrollata prima della scrittura. Mantieni alimentazione ed ENET collegati per tutta l'operazione. Non interrompere l'app.\n\nQuesta conferma non certifica la compatibilità del firmware.", icon="warning", default="no", parent=self.root):
            return
        self.ssh_verified = None
        self.coding_ok.set(False)
        self.install_success = False
        scan = dict(self.scan_result)
        local_ip = self._local_ip()
        def done(data):
            self._adapter_changed()
            self.flash_success = True
            self.known_root_vins.add(vin)
            if data.get("key"):
                self.key.set(str(data["key"]))
            self.root_text.set("Sblocco completato. Ripristina il coding, poi verifica la chiave e il login root.")
            messagebox.showinfo("Sblocco concluso", "Ora ripristina il backup precedente con BimmerCode e verifica le funzioni originali. Poi torna in Chiave e coding.\n\nNon ripetere il flash.", parent=self.root)
            self.show_stage(2)
        self._operation("Flash + Enable — NON INTERROMPERE", lambda: self.backend.flash(vin, scan["gateway"], scan["hu_ip"], local_ip), done, writes=True)

    def pick_key(self):
        selected = filedialog.askopenfilename(title="Seleziona la chiave privata id_rsa senza estensione", filetypes=[("Tutti i file", "*")], parent=self.root)
        if selected:
            if selected.lower().endswith((".pub", ".ppk", ".pub.pem")):
                messagebox.showerror("File non adatto", "Seleziona id_rsa senza estensione, non la chiave pubblica o il formato PuTTY.", parent=self.root)
                return
            self.key.set(selected)

    def recover_key(self):
        if self.demo or not self._scan_ready() or not self.scan_result.get('ssh_open'):
            return
        vin = self.scan_result['vin']
        def done(data):
            self.key.set(data['key'])
            self.root_text.set('Chiave originale recuperata sul PC. Ora leggi l’impronta HU e verifica il login root.')
        self._operation('Recupero locale della chiave originale', lambda: self.backend.recover_key(vin), done)

    def persist(self):
        if self.demo or not (self._scan_ready() and self._root_ready() and self._prerequisites() and self.coding_ok.get()):
            return
        if not messagebox.askyesno('Completa SSH senza flash', 'Installare la persistenza SSH e disattivare il debug?\n\nSi modificano servizi della HU. Non verranno eseguiti flash, enrollment o riavvii automatici.\n\nMantieni alimentazione ed ENET collegati.', default='no', icon='warning', parent=self.root):
            return
        identity = self._identity()
        self.ssh_verified = None
        def done(ok):
            if ok:
                self.ssh_verified = identity
                self.known_root_vins.add(identity[0])
                self.root_text.set('Persistenza SSH completata e login root ricontrollato. Puoi proseguire con lo Store.')
        self._operation('Persistenza SSH — NON INTERROMPERE', lambda: self.backend.persist(*identity), done, writes=True)

    def read_fingerprint(self):
        if not self.scan_result:
            return
        hu, local = self.scan_result["hu_ip"], self._local_ip()
        self.host_accepted = None
        self.ssh_verified = None
        def done(data):
            fingerprints = "\n".join(data.get("fingerprints", []))
            if not fingerprints or not data.get("key_lines"):
                raise ValueError("Il server non ha restituito chiavi utilizzabili.")
            if data.get("changed"):
                self.root_text.set("Chiave server cambiata: connessione bloccata, verificare la causa.")
                self._log("La chiave del server HU differisce da quella salvata. Nessuna sostituzione effettuata.")
                messagebox.showerror("Chiave del server cambiata", "La HU presenta una chiave diversa da quella già salvata.\n\n" + fingerprints + "\n\nVerifica prima la causa. Non sostituire la chiave salvata e non ripetere il flash come tentativo.", parent=self.root)
                return
            prompt = "HU " + hu + " sul collegamento " + local + "\n\n" + fingerprints + "\n\nConfronta con un riferimento attendibile, se disponibile. Senza un riferimento questa è fiducia al primo collegamento. Non è la fingerprint della chiave privata in connect.txt.\n\nAccettare queste chiavi del server?"
            if messagebox.askyesno("Conferma identità della HU", prompt, icon="warning", default="no", parent=self.root):
                def accepted(_):
                    self.host_accepted = (hu, local)
                    self.root_text.set("Identità server accettata. Ora verifica il login root.")
                self._operation("Salvataggio locale della chiave server", lambda: self.backend.accept_host(hu, data["key_lines"]), accepted)
            else:
                self.root_text.set("Chiave server non accettata; login bloccato.")
        self._operation("Lettura dell'impronta server HU", lambda: self.backend.host_fingerprint(hu, local), done)

    def verify_ssh(self):
        if not self.scan_result:
            return
        self.ssh_verified = None
        identity = self._identity()
        def done(ok):
            if not ok:
                self.root_text.set("Login root non riuscito. Non installare lo Store.")
                return
            self.ssh_verified = identity
            self.known_root_vins.add(identity[0])
            self.root_text.set("Accesso root confermato: id -u = 0. Nessun file applicativo modificato sulla HU.")
        self._operation("Verifica login root (sola lettura)", lambda: self.backend.verify_ssh(identity[2], identity[3], identity[4]), done)

    def verify_files(self):
        self.files_verified = False
        def done(data):
            self.files_verified = True
            self.store_text.set("Integrità del pacchetto verificata. I file saranno ricontrollati prima dell'installazione.")
        self._operation("Verifica SHA256 del pacchetto", self.backend.verify_files, done)

    def install(self):
        if self.demo or not (self._scan_ready() and self._root_ready() and self._prerequisites() and self.coding_ok.get() and self.files_verified):
            return
        if not messagebox.askyesno("Installazione MGU Store", "Installare i componenti locali sulla HU?\n\nQuesta operazione modifica file e servizi. Non esegue il flash root. Il riavvio finale sarà richiesto separatamente.\n\nMantieni alimentazione ed ENET collegati.", icon="warning", default="no", parent=self.root):
            return
        identity = self._identity()
        include_uplink = self.uplink.get()
        self.install_success = False
        def done(_):
            self.install_success = True
            self.store_text.set("Installer terminato correttamente. Vai a Riavvio e verifica per completare e controllare l'auto.")
            self.show_stage(4)
        self._operation("Installazione Store — NON INTERROMPERE", lambda: self.backend.install(identity[2], identity[3], identity[4], include_uplink=include_uplink), done, writes=True)

    def reboot(self):
        if self.demo or not (self.install_success and self._root_ready() and self.power_ok.get()):
            return
        if not messagebox.askyesno("Riavvio della HU", "Riavviare adesso la head unit, a vettura ferma?\n\nAttendi il ritorno di iDrive prima di verificare le app e le funzioni originali.", default="no", parent=self.root):
            return
        identity = self._identity()
        def done(_):
            self.ssh_verified = None
            self.host_accepted = None
            self.root_text.set("HU riavviata: per altre operazioni ripeti lettura HU e login root.")
            messagebox.showinfo("Richiesta di riavvio inviata", "Attendi iDrive, cerca MGU Store tra le app e completa i controlli della pagina. Non riflashare se la tile non compare.", parent=self.root)
        self._operation("Riavvio della HU", lambda: self.backend.reboot(identity[2], identity[3], identity[4]), done, writes=True)

    def open_guide(self):
        candidates = [self.resource_dir / "guida.html"]
        for path in candidates:
            if path.is_file():
                os.startfile(str(path))
                return
        messagebox.showinfo("Guida", "Segui i cinque passaggi dell'interfaccia. La guida completa si trova accanto al programma nel pacchetto distribuito.", parent=self.root)

    def open_log(self):
        self.log_file.flush()
        os.startfile(str(self.log_path))

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_widget.get("1.0", "end-1c"))
        self.status.set("Log copiato. Oscura VIN e dati personali prima di condividerlo.")

    def export_log(self):
        destination = filedialog.asksaveasfilename(title="Esporta il log (può contenere VIN)", defaultextension=".txt", initialfile=self.log_path.stem + ".txt", filetypes=[("Testo", "*.txt")], parent=self.root)
        if destination:
            Path(destination).write_text(self.log_widget.get("1.0", "end-1c"), encoding="utf-8")
            self.status.set("Log esportato. Esaminalo prima di condividerlo.")

    def close(self):
        if self.busy:
            messagebox.showwarning("Operazione in corso", "Attendi la conclusione prima di chiudere l'app." + ("\nNon interrompere alimentazione, ENET o processo durante una scrittura." if self.write_busy else ""), parent=self.root)
            return
        self.closed = True
        self.log_file.close()
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="MGU Assistant — interfaccia Windows guidata")
    parser.add_argument("--demo", action="store_true", help="dati dimostrativi, nessuna operazione sulla vettura")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--resource-dir", type=Path)
    parser.add_argument("--worker", choices=["flash", "persist"])
    parser.add_argument("--key")
    parser.add_argument("--vin")
    parser.add_argument("--gateway")
    parser.add_argument("--hu-ip")
    parser.add_argument("--local-ip")
    parser.add_argument("--ui-smoke", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--self-test", action="store_true", help="verifica locale di dipendenze e risorse, senza contattare la vettura")
    args = parser.parse_args(argv)
    resource_dir = args.resource_dir or app_folder() / "resources"
    state_dir = args.state_dir or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MGUAssistant"
    if args.self_test:
        _restore_worker_streams()
        try:
            print("Test locale del log: à → • ✓", file=sys.stderr, flush=True)
            tester = Backend(resource_dir, state_dir, lambda line: print(str(line), file=sys.stderr), demo=True)
            result = {"integrity": tester.verify_files(), "dependencies": tester.self_check(),
                      "logging": "UTF-8: à → • ✓", "version": VERSION}
            print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
            return 0
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), flush=True)
            return 1
    if args.worker:
        _restore_worker_streams()
        if args.demo or args.ui_smoke:
            print("Modalità demo: worker di scrittura bloccato.", file=sys.stderr, flush=True)
            return 1
        try:
            result = run_root_worker(args, state_dir, resource_dir)
            return int(result or 0)
        except BaseException as exc:
            print("ERRORE worker:", str(exc), file=sys.stderr, flush=True)
            return 1
    root = tk.Tk()
    application = MGUApp(root, resource_dir, state_dir, demo=args.demo or args.ui_smoke)
    if args.ui_smoke:
        def smoke():
            for i in range(5):
                application.show_stage(i)
                root.update_idletasks()
            application.show_stage(0)
            application.close()
        root.after(250, smoke)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
