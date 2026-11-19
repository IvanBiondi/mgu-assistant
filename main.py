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

from i18n import tr

from backend import Backend, run_root_worker

APP_NAME = "MGU Assistant"
VERSION = "0.2.0-beta.3"
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
        ("1", tr("Connection"), tr("Check the PC, ENET and head unit")),
        ("2", tr("Backup and unlock"), tr("Prepare before unlocking")),
        ("3", tr("Key and coding"), tr("Verify root access and coding recovery")),
        ("4", tr("Install Store"), tr("Install the offline components")),
        ("5", tr("Restart and verify"), tr("Finish and check vehicle functions")),
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
        self.pc_text = tk.StringVar(value=tr("Not checked. No connection starts automatically."))
        self.hu_text = tk.StringVar(value="Connect ENET, select the Ethernet adapter, then click Read HU.")
        self.root_text = tk.StringVar(value=tr("Root access not verified"))
        self.store_text = tk.StringVar(value=tr("Files not verified · not installed"))
        self.backup_text = tk.StringVar(value=tr("No backup selected"))
        self.status = tk.StringVar(value=tr("Ready · no vehicle operation in progress"))
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
        self._log("MGU Assistant " + VERSION + (" — DEMO MODE: no vehicle operations." if demo else " — no operation started."))
        self._log(tr("Local logs may contain VINs, IP addresses and paths. Review them before sharing. Key contents are not intentionally logged."))
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
            tk.Label(lower, text=tr("DEMO · WRITES BLOCKED"), bg="#72531f", fg="#fff0bd", font=("Segoe UI", 9, "bold"), padx=7, pady=8).pack(fill="x", pady=(0, 12))
        tk.Label(lower, text=tr("Independent tool\nNot BMW-certified\nVersion ") + VERSION,
                 bg=NAVY, fg="#aabbd2", justify="left", font=("Segoe UI", 9)).pack(anchor="w")

        right = ttk.Frame(self.root, padding=(24, 18, 24, 12))
        right.pack(fill="both", expand=True)
        top = ttk.Frame(right)
        top.pack(fill="x", pady=(0, 13))
        title_area = ttk.Frame(top)
        title_area.pack(side="left", fill="x", expand=True)
        ttk.Label(title_area, textvariable=self.stage_title, font=("Segoe UI Semibold", 22)).pack(anchor="w")
        ttk.Label(title_area, textvariable=self.stage_subtitle, foreground=MUTED).pack(anchor="w", pady=(4, 0))
        ttk.Button(top, text=tr("Open guide"), command=self.open_guide).pack(side="right", padx=(8, 0))
        ttk.Button(top, text=tr("Open log"), command=self.open_log).pack(side="right")

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
        ttk.Label(log_head, text=tr("Activity log"), font=("Segoe UI Semibold", 11)).pack(side="left")
        ttk.Button(log_head, text=tr("Copy"), command=self.copy_log).pack(side="right", padx=(7, 0))
        ttk.Button(log_head, text=tr("Export…"), command=self.export_log).pack(side="right")
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
        card = self.card(page, tr("Connect the PC to the vehicle"))
        self.text(card, tr("Park the vehicle with the ignition on. Connect the ENET cable to the OBD port and the PC Ethernet adapter. The initial check only reads data; it does not enable SSH or flash the HU."))
        ttk.Label(card, textvariable=self.pc_text, style="Muted.TLabel", wraplength=800).pack(anchor="w", pady=(0, 9))
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "pc", tr("Check PC and adapters"), self.check_pc, "Accent.TButton")
        card = self.card(page, tr("ENET Ethernet adapter"))
        self.text(card, tr("Select the wired ENET adapter connected to the car. Link-local and private IPv4 addresses are listed. The PC, gateway and HU must share its subnet. Network settings are not changed."), True)
        self.adapter_combo = ttk.Combobox(card, textvariable=self.adapter, state="readonly", width=70)
        self.adapter_combo.pack(fill="x", pady=(0, 8))
        self.controls.append((self.adapter_combo, "readonly"))
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "scan", tr("Read HU"), self.scan, "Accent.TButton")
        card = self.card(page, tr("Head unit identification"))
        ttk.Label(card, textvariable=self.hu_text, style="Body.TLabel", wraplength=800, justify="left").pack(anchor="w", fill="x", pady=(0, 11))
        self.svk_table = ttk.Treeview(card, columns=("type", "id", "version"), show="headings", height=4)
        for name, label, width in (("type", tr("Component"), 130), ("id", tr("Identifier"), 210), ("version", tr("Version"), 210)):
            self.svk_table.heading(name, text=label); self.svk_table.column(name, width=width, stretch=True)
        self.svk_table.pack(fill="x")
        self.text(card, tr("The project filter does not certify every firmware. Stop if the VIN differs, the HU is unrecognized or CAFD is missing."), True)

    def _root_page(self, page):
        card = self.card(page, tr("Coding backup: manual step with BimmerCode"))
        self.text(card, tr("Use BimmerCode to read HU_MGU and export a valid backup BEFORE unlocking. This app does not create or restore BimmerCode backups and cannot validate their contents."))
        ttk.Label(card, textvariable=self.backup_text, style="Muted.TLabel", wraplength=800).pack(anchor="w", fill="x")
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "backup_file", tr("Select backup file…"), self.pick_backup)
        self.button(row, "backup_folder", tr("Select folder…"), lambda: self.pick_backup(folder=True))
        card = self.card(page, tr("Before modifying the HU"))
        self.check(card, self.backup_ok, tr("I have an exported original backup and a usable recovery procedure."))
        self.check(card, self.hu_ok, tr("I have verified HU_MGU, iDrive 7 and my vehicle software version."))
        self.check(card, self.power_ok, tr("The vehicle is parked with suitable stabilized power; the PC is powered and will not sleep."))
        self.check(card, self.physical_key, tr("I have the physical key. A coding backup does not preserve Digital Key pairings."))
        card = self.card(page, tr("Initial unlock: Flash + Enable"))
        self.text(card, tr("Reprograms the HU and enables SSH using the original project procedure. It can erase coding/CAFD and Digital Key pairings or leave the HU unusable. Skip this step if root access already works."))
        self.text(card, tr("The procedure uses ID7, leaves the advanced unique-key option disabled and requires debug to be off at completion. Force options, Fix key and automatic repairs are not available."), True)
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "flash", tr("Flash + Enable…"), self.flash, "Danger.TButton")
        self.flash_hint = ttk.Label(card, text="", style="Muted.TLabel", wraplength=800)
        self.flash_hint.pack(anchor="w", fill="x", pady=(11, 0))

    def _key_page(self, page):
        card = self.card(page, tr("Root private key"))
        self.text(card, tr("Choose id_rsa without an extension, not id_rsa.pub or .ppk. After a successful unlock, the app selects the path returned by the project. Do not share the key contents in chat."))
        entry = ttk.Entry(card, textvariable=self.key)
        entry.pack(fill="x", pady=(0, 7)); self.controls.append((entry, "normal"))
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "key", tr("Select id_rsa…"), self.pick_key)
        self.button(row, "recover_key", tr("Recover original key on PC"), self.recover_key)
        self.text(card, tr("If flashing finished but the app stopped before exporting the key, you can recover the bootstrap key included in the project. This does not modify the vehicle or guarantee a successful login."), True)
        card = self.card(page, tr("HU identity and root verification"))
        self.text(card, tr("First read and confirm the HU SERVER key over the direct ENET connection. This fingerprint differs from your private key fingerprint listed in connect.txt. Without an independent reference, this is trust on first use."))
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "fingerprint", tr("Read HU fingerprint…"), self.read_fingerprint)
        self.button(row, "ssh", tr("Verify root access"), self.verify_ssh, "Accent.TButton")
        ttk.Label(card, textvariable=self.root_text, style="Body.TLabel", wraplength=800).pack(anchor="w", pady=(12, 0))
        card = self.card(page, tr("Coding recovery and function checks"))
        self.text(card, tr("If you flashed the HU, wait for completion, close diagnostic connections and restore the ORIGINAL backup in BimmerCode. Then reconnect ENET to the PC. Resolve any missing functions before installing the Store."))
        self.check(card, self.coding_ok, tr("I have restored coding if needed and checked the original HU functions."))
        card = self.card(page, tr("Complete existing SSH — no new flash"))
        self.text(card, tr("After an interruption following the flash, verify root login and coding first. This action installs SSH persistence and disables debug using the original procedure. It changes HU services without flashing, enrollment or automatic restarts."))
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "persist", tr("Complete SSH persistence…"), self.persist, "Accent.TButton")

    def _store_page(self, page):
        card = self.card(page, tr("Local components, verified before use"))
        self.text(card, tr("The upstream installer uses the bundled components. The first installation does not need Internet access; updates and additional apps may need it. SHA-256 checks detect changes, not BMW compatibility."))
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "files", tr("Verify package files"), self.verify_files)
        ttk.Label(card, textvariable=self.store_text, style="Body.TLabel", wraplength=800).pack(anchor="w", fill="x", pady=(12, 0))
        card = self.card(page, tr("First Store installation"))
        self.text(card, tr("Installs Store, deploy, updater, app-privacy, HU Python and renderer. It writes files and changes HU services. The installer does not perform the root unlock. The final restart is a separate action."))
        self.check(card, self.uplink, tr("Include Internet uplink (full project configuration)"))
        self.text(card, tr("App-privacy changes application reporting; it does not guarantee invisibility or warranty coverage. Configure Store Wi-Fi/Internet on the HU."), True)
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "install", tr("Install MGU Store…"), self.install, "Accent.TButton")
        self.install_hint = ttk.Label(card, text="", style="Muted.TLabel", wraplength=800)
        self.install_hint.pack(anchor="w", fill="x", pady=(11, 0))

    def _finish_page(self, page):
        card = self.card(page, tr("Head unit restart"))
        self.text(card, tr("After a successful installation, restart the HU with the vehicle parked to complete activation. Do not turn off the vehicle or disconnect power while an operation is running."))
        row = ttk.Frame(card, style="Card.TFrame"); row.pack(fill="x")
        self.button(row, "reboot", tr("Restart HU…"), self.reboot, "Accent.TButton")
        card = self.card(page, tr("In-car checks"))
        for var, text in zip(self.final_checks, (
                tr("MGU Store appears in the app list and opens."),
                tr("Audio, language, menus and original settings work correctly."),
                tr("I have safely checked the camera and other original functions."),
                tr("I have stored coding backups, keys and logs in a safe place."))):
            self.check(card, var, text)
        self.text(card, tr("For Internet access, use Store Settings → Wi-Fi and your phone hotspot, then check Online. An online PC does not automatically connect the HU to the Internet. Install only ID7-compatible apps, one at a time."), True)
        self.text(card, tr("If something does not work, keep the log, do not reflash and do not apply automatic repairs. Checked boxes are user confirmations, not automated tests."), True)

    def show_stage(self, index):
        for page in self.pages:
            page.pack_forget()
        self.current_stage = index
        self.pages[index].pack(fill="both", expand=True)
        number, title, subtitle = self.STAGES[index]
        self.stage_title.set(title)
        self.stage_subtitle.set("STEP " + number + " OF 5  ·  " + subtitle)
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
        self.hu_text.set(tr("Adapter changed: read the HU again."))
        self.root_text.set(tr("Root access not verified"))
        for item in self.svk_table.get_children():
            self.svk_table.delete(item)
        self._refresh()

    def _key_changed(self, *_):
        self.ssh_verified = None
        self.install_success = False
        self.root_text.set(tr("Key changed: verify root access again."))
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
            self.flash_hint.configure(text=tr("Demo mode: all vehicle writes are blocked."))
        elif self._flash_attempted():
            self.flash_hint.configure(text=tr("A flash attempt is already recorded for this VIN; another attempt is blocked even after restarting. See the recovery guide and keep the log."))
        elif self._root_seen() or self.flash_success or (self.scan_result or {}).get('ssh_open'):
            self.flash_hint.configure(text=tr("SSH is open or unlocking already succeeded: do not flash again. Verify login on the Key and coding page."))
        else:
            self.flash_hint.configure(text=tr("Requires a valid HU reading, a selected backup and all confirmations. The reading is repeated immediately before flashing."))
        self.install_hint.configure(text=tr("Requires: identified HU, confirmed backup and power, verified root login, checked coding and verified files.") if not self.demo else tr("Demo mode: installation is disabled."))

    def thread_log(self, line):
        self.events.put(("log", str(line)))

    def _log(self, text):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = "[" + stamp + "] " + str(text).rstrip() + "\n"
        try:
            self.log_file.write(line)
        except OSError:
            if not self.log_error:
                line += tr("LOG NOT WRITABLE: save the text from this window. No new write will start; the current write must finish.\n")
            self.log_error = True
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", line)
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _operation(self, title, operation, on_success=None, writes=False):
        if self.busy:
            return
        if writes and self.log_error:
            messagebox.showerror(tr("Log not writable"), tr("Resolve the log problem before starting another operation. Save the text from this window."), parent=self.root)
            return
        if writes and self.demo:
            messagebox.showinfo(tr("Demo"), tr("Vehicle operations are blocked in demo mode."), parent=self.root)
            return
        self.busy = True
        self.write_busy = writes
        self.status.set(title + (" · do not disconnect or close the app" if writes else " · operation in progress"))
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
                        self._log(title + ": completed.")
                        self.status.set("Completed · " + title)
                        if callback:
                            try:
                                callback(result)
                            except Exception as exc:
                                if was_writing:
                                    self._adapter_changed()
                                self._log("Unusable result: " + str(exc))
                                self.status.set(tr("Result needs review · check the log"))
                                messagebox.showerror(tr("Result needs review"), str(exc), parent=self.root)
                    else:
                        if was_writing:
                            self._adapter_changed()
                            self.hu_text.set(tr("Write result needs review: read the HU again. Do not repeat the flash."))
                        title, error = payload
                        self._log(title + ": ERROR — " + error)
                        self.status.set(tr("Operation failed · check the log"))
                        messagebox.showerror(tr("Operation failed"), error + tr("\n\nKeep the log. No repair or repeat flash will start automatically."), parent=self.root)
                    self._refresh()
        except queue.Empty:
            pass
        self.root.after(70, self._poll)

    def check_pc(self):
        def done(data):
            self.pc_checked = bool(data.get("ssh"))
            self.pc_text.set(tr("OpenSSH available") if self.pc_checked else tr("OpenSSH Client is unavailable: install it through Windows Optional Features."))
            self.adapters = {}
            for item in data.get("adapters", []):
                label = tr('{v0}  ·  {v1}  ·  index {v2}').format(v0=item['name'], v1=item['ip'], v2=item['index'])
                self.adapters[label] = item
            self.adapter_combo.configure(values=list(self.adapters))
            self.adapter.set(next(iter(self.adapters)) if len(self.adapters) == 1 else "")
            if not self.adapters:
                self.pc_text.set(self.pc_text.get() + " · No active ENET Ethernet adapter: check the cable, adapter and ignition.")
        self._operation(tr("Local PC check"), self.backend.check_pc, done)

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
            compatibility = tr("MGU filter passed") if data.get("supported") else tr("Unsupported HU: stop")
            coding = tr("CAFD present") if data.get("cafd_ok") else tr("CAFD missing/invalid: stop")
            self.hu_text.set(tr('VIN: {v0}\nGateway: {v1}   •   HU: {v2}\n{v3}   •   {v4}\nSSH port: {v5}').format(v0=data.get('vin', 'unavailable'), v1=data.get('gateway', '—'), v2=data.get('hu_ip', '—'), v3=compatibility, v4=coding, v5='open (does not prove root login)' if data.get('ssh_open') else 'unreachable'))
            for item in self.svk_table.get_children():
                self.svk_table.delete(item)
            for record in data.get("svk", []):
                self.svk_table.insert("", "end", values=(record.get("type"), record.get("id"), record.get("version")))
            self.root_text.set(tr("Root access not verified"))
        self._operation(tr("Read-only HU check"), lambda: self.backend.scan(local_ip), done)

    def pick_backup(self, folder=False):
        selected = filedialog.askdirectory(title=tr("Select the exported backup folder"), parent=self.root) if folder else filedialog.askopenfilename(title=tr("Select a coding backup made before flashing"), parent=self.root)
        if selected:
            self.backup.set(selected)
            self.backup_ok.set(False)
            self.backup_text.set(selected + tr("\nPath recorded; you must confirm backup validity and recoverability yourself."))

    def flash(self):
        if self.demo or not self._scan_ready() or not self._prerequisites() or self._root_seen() or self._flash_attempted() or self.flash_success or self.scan_result.get('ssh_open'):
            return
        vin = self.scan_result["vin"]
        confirmation = simpledialog.askstring(tr("Confirm VIN before flashing"), tr("Flashing can erase coding/CAFD and Digital Key pairings and damage the HU.\n\nDetected VIN: ") + vin + tr("\n\nCompare it with the vehicle and type it again to continue:"), parent=self.root)
        if confirmation is None or confirmation.strip().upper() != vin.upper():
            self._log(tr("Flash not started: VIN not confirmed."))
            return
        if not messagebox.askyesno(tr("Final confirmation: HU reprogramming"), tr("Start Flash + Enable on your vehicle?\n\nThe HU reading will be checked again before writing. Keep power and ENET connected throughout the operation. Do not interrupt the app.\n\nThis confirmation does not certify firmware compatibility."), icon="warning", default="no", parent=self.root):
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
            self.root_text.set("Unlock completed. Restore coding, then verify the key and root login.")
            messagebox.showinfo(tr("Unlock completed"), tr("Now restore the original backup with BimmerCode and check the original functions. Then return to Key and coding.\n\nDo not repeat the flash."), parent=self.root)
            self.show_stage(2)
        self._operation(tr("Flash + Enable — DO NOT INTERRUPT"), lambda: self.backend.flash(vin, scan["gateway"], scan["hu_ip"], local_ip), done, writes=True)

    def pick_key(self):
        selected = filedialog.askopenfilename(title=tr("Select the id_rsa private key without an extension"), filetypes=[(tr("All files"), "*")], parent=self.root)
        if selected:
            if selected.lower().endswith((".pub", ".ppk", ".pub.pem")):
                messagebox.showerror(tr("Unsuitable file"), tr("Select id_rsa without an extension, not the public key or PuTTY format."), parent=self.root)
                return
            self.key.set(selected)

    def recover_key(self):
        if self.demo or not self._scan_ready() or not self.scan_result.get('ssh_open'):
            return
        vin = self.scan_result['vin']
        def done(data):
            self.key.set(data['key'])
            self.root_text.set(tr('Original key recovered on the PC. Now read the HU fingerprint and verify root login.'))
        self._operation(tr('Local recovery of the original key'), lambda: self.backend.recover_key(vin), done)

    def persist(self):
        if self.demo or not (self._scan_ready() and self._root_ready() and self._prerequisites() and self.coding_ok.get()):
            return
        if not messagebox.askyesno(tr('Complete SSH without flashing'), tr('Install SSH persistence and disable debug?\n\nThis changes HU services. No flashing, enrollment or automatic restarts will be performed.\n\nKeep power and ENET connected.'), default='no', icon='warning', parent=self.root):
            return
        identity = self._identity()
        self.ssh_verified = None
        def done(ok):
            if ok:
                self.ssh_verified = identity
                self.known_root_vins.add(identity[0])
                self.root_text.set(tr('SSH persistence completed and root login checked again. You can continue with the Store.'))
        self._operation(tr('SSH persistence — DO NOT INTERRUPT'), lambda: self.backend.persist(*identity), done, writes=True)

    def read_fingerprint(self):
        if not self.scan_result:
            return
        hu, local = self.scan_result["hu_ip"], self._local_ip()
        self.host_accepted = None
        self.ssh_verified = None
        def done(data):
            fingerprints = "\n".join(data.get("fingerprints", []))
            if not fingerprints or not data.get("key_lines"):
                raise ValueError(tr("The server did not return usable keys."))
            if data.get("changed"):
                self.root_text.set(tr("Server key changed: connection blocked. Investigate the cause."))
                self._log(tr("The HU server key differs from the saved key. No replacement was made."))
                messagebox.showerror(tr("Server key changed"), tr("The HU presents a different key from the one already saved.\n\n") + fingerprints + tr("\n\nInvestigate the cause first. Do not replace the saved key or try flashing again."), parent=self.root)
                return
            prompt = "HU " + hu + " over connection " + local + "\n\n" + fingerprints + tr("\n\nCompare with a trusted reference if available. Without a reference, this is trust on first use. This is not the private key fingerprint in connect.txt.\n\nAccept these server keys?")
            if messagebox.askyesno(tr("Confirm HU identity"), prompt, icon="warning", default="no", parent=self.root):
                def accepted(_):
                    self.host_accepted = (hu, local)
                    self.root_text.set(tr("Server identity accepted. Now verify root login."))
                self._operation(tr("Saving the server key locally"), lambda: self.backend.accept_host(hu, data["key_lines"]), accepted)
            else:
                self.root_text.set(tr("Server key not accepted; login blocked."))
        self._operation(tr("Reading the HU server fingerprint"), lambda: self.backend.host_fingerprint(hu, local), done)

    def verify_ssh(self):
        if not self.scan_result:
            return
        self.ssh_verified = None
        identity = self._identity()
        def done(ok):
            if not ok:
                self.root_text.set(tr("Root login failed. Do not install the Store."))
                return
            self.ssh_verified = identity
            self.known_root_vins.add(identity[0])
            self.root_text.set(tr("Root access confirmed: id -u = 0. No application files changed on the HU."))
        self._operation(tr("Verify root login (read-only)"), lambda: self.backend.verify_ssh(identity[2], identity[3], identity[4]), done)

    def verify_files(self):
        self.files_verified = False
        def done(data):
            self.files_verified = True
            self.store_text.set(tr("Package integrity verified. Files will be checked again before installation."))
        self._operation(tr("Verify package SHA-256"), self.backend.verify_files, done)

    def install(self):
        if self.demo or not (self._scan_ready() and self._root_ready() and self._prerequisites() and self.coding_ok.get() and self.files_verified):
            return
        if not messagebox.askyesno(tr("MGU Store installation"), tr("Install the local components on the HU?\n\nThis operation changes files and services. It does not perform a root flash. The final restart will be requested separately.\n\nKeep power and ENET connected."), icon="warning", default="no", parent=self.root):
            return
        identity = self._identity()
        include_uplink = self.uplink.get()
        self.install_success = False
        def done(_):
            self.install_success = True
            self.store_text.set(tr("Installer completed successfully. Go to Restart and verify to finish and check the vehicle."))
            self.show_stage(4)
        self._operation(tr("Store installation — DO NOT INTERRUPT"), lambda: self.backend.install(identity[2], identity[3], identity[4], include_uplink=include_uplink), done, writes=True)

    def reboot(self):
        if self.demo or not (self.install_success and self._root_ready() and self.power_ok.get()):
            return
        if not messagebox.askyesno(tr("HU restart"), tr("Restart the head unit now, with the vehicle parked?\n\nWait for iDrive to return before checking apps and original functions."), default="no", parent=self.root):
            return
        identity = self._identity()
        def done(_):
            self.ssh_verified = None
            self.host_accepted = None
            self.root_text.set(tr("HU restarted: read the HU and verify root login again before further operations."))
            messagebox.showinfo(tr("Restart request sent"), tr("Wait for iDrive, find MGU Store in the app list and complete the checks on this page. Do not reflash if the tile is missing."), parent=self.root)
        self._operation(tr("HU restart"), lambda: self.backend.reboot(identity[2], identity[3], identity[4]), done, writes=True)

    def open_guide(self):
        candidates = [self.resource_dir / "guida.html"]
        for path in candidates:
            if path.is_file():
                os.startfile(str(path))
                return
        messagebox.showinfo(tr("Guide"), tr("Follow the five steps in the interface. The full guide is included alongside the application in the release package."), parent=self.root)

    def open_log(self):
        self.log_file.flush()
        os.startfile(str(self.log_path))

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_widget.get("1.0", "end-1c"))
        self.status.set(tr("Log copied. Remove VINs and personal data before sharing."))

    def export_log(self):
        destination = filedialog.asksaveasfilename(title=tr("Export log (may contain VINs)"), defaultextension=".txt", initialfile=self.log_path.stem + ".txt", filetypes=[(tr("Text"), "*.txt")], parent=self.root)
        if destination:
            Path(destination).write_text(self.log_widget.get("1.0", "end-1c"), encoding="utf-8")
            self.status.set(tr("Log exported. Review it before sharing."))

    def close(self):
        if self.busy:
            messagebox.showwarning(tr("Operation in progress"), tr("Wait for completion before closing the app.") + (tr("\nDo not interrupt power, ENET or the process during a write.") if self.write_busy else ""), parent=self.root)
            return
        self.closed = True
        self.log_file.close()
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="MGU Assistant — guided Windows interface")
    parser.add_argument("--demo", action="store_true", help=tr("sample data, no vehicle operations"))
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--resource-dir", type=Path)
    parser.add_argument("--worker", choices=["flash", "persist"])
    parser.add_argument("--key")
    parser.add_argument("--vin")
    parser.add_argument("--gateway")
    parser.add_argument("--hu-ip")
    parser.add_argument("--local-ip")
    parser.add_argument("--ui-smoke", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--self-test", action="store_true", help=tr("check local dependencies and resources without contacting a vehicle"))
    args = parser.parse_args(argv)
    resource_dir = args.resource_dir or app_folder() / "resources"
    state_dir = args.state_dir or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MGUAssistant"
    if args.self_test:
        _restore_worker_streams()
        try:
            print("Local logging test: à → • ✓", file=sys.stderr, flush=True)
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
            print(tr("Demo mode: write worker blocked."), file=sys.stderr, flush=True)
            return 1
        try:
            result = run_root_worker(args, state_dir, resource_dir)
            return int(result or 0)
        except BaseException as exc:
            print("Worker ERROR:", str(exc), file=sys.stderr, flush=True)
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
