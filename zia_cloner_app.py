"""
Simple desktop GUI for ZIA Backup & Restore.
"""
import contextlib
import copy
import io
import json
import os
import queue
import re
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import config_manager
import sync
from app_paths import APP_DIR
from zia_client import AUTH_MODE_LEGACY, AUTH_MODE_ONEAPI, normalise_legacy_cloud


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
APP_NAME = "ZIA Backup & Restore"


class QueueWriter(io.TextIOBase):
    def __init__(self, output_queue):
        self.output_queue = output_queue

    def write(self, text):
        if text:
            clean = ANSI_RE.sub("", text)
            if "API call estimate" in clean or "estimated API call(s)" in clean or "Estimated minimum time:" in clean or "Estimate uses conservative defaults:" in clean:
                self.output_queue.put(("estimate", clean))
            else:
                self.output_queue.put(("log", clean))
        return len(text)

    def flush(self):
        return None


class ZIAClonerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1120x760")
        self.minsize(960, 640)
        self.output_queue = queue.Queue()
        self.worker = None
        self.vars = {}

        self._configure_style()
        self._build_ui()
        self._load_config()
        self.after(250, self._show_startup_warning)
        self.after(100, self._drain_output)

    def _configure_style(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Danger.TButton", foreground="#8b1a1a")

    def _show_startup_warning(self):
        messagebox.showwarning(
            "Use with care",
            "ZIA Backup & Restore can make significant configuration changes through the Zscaler API.\n\n"
            "Backups, restores, sync operations, updates, and deletes may affect live tenant policy and user traffic. "
            "Review all generated reports carefully, run preview/dry-run operations first, and validate the workflow in a non-production tenant before using it in production.\n\n"
            "Proceed only if you understand the impact of the selected operation.",
        )

    def _build_ui(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1, uniform="cols")
        root.columnconfigure(1, weight=1, uniform="cols")
        root.rowconfigure(2, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_NAME, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=f"Data folder: {APP_DIR}").grid(row=1, column=0, sticky="w")
        ttk.Button(header, text="Open Data Folder", command=self._open_data_folder).grid(row=0, column=1, rowspan=2, sticky="e")

        settings = ttk.LabelFrame(root, text="Mode and sync settings", style="Section.TLabelframe", padding=10)
        settings.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        for i in range(6):
            settings.columnconfigure(i, weight=1)
        self.vars["report_only"] = tk.BooleanVar()
        self.vars["no_delete"] = tk.BooleanVar()
        self.vars["auto_activate"] = tk.BooleanVar(value=True)
        self.vars["sync_sensitive"] = tk.BooleanVar()
        self.vars["include_slow_readonly"] = tk.BooleanVar()
        ttk.Checkbutton(settings, text="Report only", variable=self.vars["report_only"], command=self._toggle_target_state).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(settings, text="Do not delete target-only objects", variable=self.vars["no_delete"]).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(settings, text="Auto activate changes", variable=self.vars["auto_activate"]).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(settings, text="Include users/groups", variable=self.vars["sync_sensitive"]).grid(row=0, column=3, sticky="w")
        ttk.Checkbutton(settings, text="Include slow read-only inventory", variable=self.vars["include_slow_readonly"]).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(settings, text="Save Config", command=self._save_config).grid(row=0, column=4, sticky="e")
        ttk.Button(settings, text="Reload", command=self._load_config).grid(row=0, column=5, sticky="e")

        self.tenant_frames = {}
        self._build_tenant_frame(root, "tenant_a", "Source / report tenant", 0)
        self._build_tenant_frame(root, "tenant_b", "Target tenant", 1)

        actions = ttk.Frame(root)
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 10))
        actions.columnconfigure(0, weight=1, uniform="actions")
        actions.columnconfigure(1, weight=1, uniform="actions")
        actions.columnconfigure(2, weight=1, uniform="actions")

        test_actions = ttk.LabelFrame(actions, text="Test", style="Section.TLabelframe", padding=10)
        report_actions = ttk.LabelFrame(actions, text="Report and Backup", style="Section.TLabelframe", padding=10)
        sync_actions = ttk.LabelFrame(actions, text="Sync", style="Section.TLabelframe", padding=10)
        test_actions.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        report_actions.grid(row=0, column=1, sticky="nsew", padx=6)
        sync_actions.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        for frame in (test_actions, report_actions, sync_actions):
            frame.columnconfigure(0, weight=1)
            frame.columnconfigure(1, weight=1)

        ttk.Button(test_actions, text="Check Authentication", command=lambda: self._run_action("Check Authentication", self._check_authentication)).grid(row=0, column=0, columnspan=2, sticky="ew", padx=3, pady=3)
        ttk.Button(test_actions, text="Test Source", command=lambda: self._run_action("Test Source", self._test_tenant, "tenant_a")).grid(row=1, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(test_actions, text="Test Target", command=lambda: self._run_action("Test Target", self._test_tenant, "tenant_b")).grid(row=1, column=1, sticky="ew", padx=3, pady=3)

        ttk.Button(report_actions, text="Backup", command=lambda: self._run_command("Backup", sync.cmd_backup, "both")).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(report_actions, text="Full Report", command=lambda: self._run_command("Full Report", sync.cmd_full_report, "both")).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(report_actions, text="Open Report", command=self._open_report).grid(row=1, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(report_actions, text="Clear Log", command=lambda: self.log.delete("1.0", "end")).grid(row=1, column=1, sticky="ew", padx=3, pady=3)

        ttk.Button(sync_actions, text="Dry Run", command=lambda: self._run_command("Dry Run", sync.cmd_dry_run)).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(sync_actions, text="Apply Sync", style="Danger.TButton", command=self._confirm_sync).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(sync_actions, text="Restore Preview", command=lambda: self._choose_restore_backup(dry_run=True)).grid(row=1, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(sync_actions, text="Restore Backup", style="Danger.TButton", command=self._confirm_restore).grid(row=1, column=1, sticky="ew", padx=3, pady=3)

        estimate_frame = ttk.LabelFrame(root, text="Estimate", style="Section.TLabelframe", padding=8)
        estimate_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        estimate_frame.columnconfigure(0, weight=1)
        self.estimate_text = tk.StringVar(value="Run Backup, Dry Run, Restore Preview, or Sync to calculate API calls and estimated time.")
        ttk.Label(estimate_frame, textvariable=self.estimate_text, wraplength=1040, justify="left").grid(row=0, column=0, sticky="ew")

        log_frame = ttk.LabelFrame(root, text="Output", style="Section.TLabelframe", padding=8)
        log_frame.grid(row=5, column=0, columnspan=2, sticky="nsew")
        root.rowconfigure(5, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, wrap="word", height=14, font=("Consolas", 10), bg="#101418", fg="#e8eef2", insertbackground="#e8eef2")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

    def _build_tenant_frame(self, parent, key, title, column):
        frame = ttk.LabelFrame(parent, text=title, style="Section.TLabelframe", padding=10)
        frame.grid(row=2, column=column, sticky="nsew", padx=(0, 6) if column == 0 else (6, 0))
        self.tenant_frames[key] = frame
        for i in range(4):
            frame.columnconfigure(i, weight=1)

        self.vars[f"{key}.auth_mode"] = tk.StringVar(value=AUTH_MODE_ONEAPI)
        ttk.Label(frame, text="Auth").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(frame, text="OneAPI", variable=self.vars[f"{key}.auth_mode"], value=AUTH_MODE_ONEAPI, command=self._refresh_auth_fields).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(frame, text="Legacy", variable=self.vars[f"{key}.auth_mode"], value=AUTH_MODE_LEGACY, command=self._refresh_auth_fields).grid(row=0, column=2, sticky="w")

        fields = [
            ("label", "Label", False),
            ("oneapi_cloud", "OneAPI cloud", False),
            ("vanity_domain", "Vanity domain", False),
            ("client_id", "Client ID", False),
            ("client_secret", "Client secret", True),
            ("partner_id", "Partner ID (optional)", False),
            ("cloud", "Legacy cloud", False),
            ("username", "Username", False),
            ("password", "Password", True),
            ("api_key", "API key", True),
        ]
        for row, (name, label, secret) in enumerate(fields, start=1):
            var_name = f"{key}.{name}"
            self.vars[var_name] = tk.StringVar()
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
            if name == "oneapi_cloud":
                entry = ttk.Combobox(
                    frame,
                    textvariable=self.vars[var_name],
                    values=config_manager.KNOWN_ONEAPI_CLOUDS,
                    state="readonly",
                )
            elif name == "cloud":
                entry = ttk.Combobox(
                    frame,
                    textvariable=self.vars[var_name],
                    values=config_manager.KNOWN_CLOUDS,
                )
            else:
                entry = ttk.Entry(frame, textvariable=self.vars[var_name], show="*" if secret else "")
            entry.grid(row=row, column=1, columnspan=3, sticky="ew", pady=2)
            setattr(self, f"entry_{key}_{name}", entry)

    def _default_config(self):
        return copy.deepcopy(config_manager.DEFAULT_CONFIG)

    def _load_config(self):
        cfg = config_manager.load() or self._default_config()
        for key in ("tenant_a", "tenant_b"):
            tenant = cfg.get(key, {})
            for name in ("label", "oneapi_cloud", "vanity_domain", "client_id", "client_secret", "partner_id", "cloud", "username", "password", "api_key"):
                value = tenant.get(name, "")
                if name == "cloud":
                    value = normalise_legacy_cloud(value)
                self.vars[f"{key}.{name}"].set(value)
            self.vars[f"{key}.auth_mode"].set(config_manager.tenant_auth_mode(tenant))
        sync_cfg = cfg.get("sync", {})
        self.vars["report_only"].set(bool(sync_cfg.get("report_only", False)))
        self.vars["no_delete"].set(bool(sync_cfg.get("no_delete", False)))
        self.vars["auto_activate"].set(bool(sync_cfg.get("auto_activate", True)))
        self.vars["sync_sensitive"].set(bool(sync_cfg.get("sync_sensitive", False)))
        self.vars["include_slow_readonly"].set(bool(sync_cfg.get("include_slow_readonly", False)))
        self._refresh_auth_fields()
        self._toggle_target_state()
        self._append_log(f"Loaded config from {config_manager.CONFIG_PATH}\n")

    def _collect_config(self):
        cfg = self._default_config()
        for key in ("tenant_a", "tenant_b"):
            for name in ("label", "oneapi_cloud", "vanity_domain", "client_id", "client_secret", "partner_id", "cloud", "username", "password", "api_key"):
                cfg[key][name] = self.vars[f"{key}.{name}"].get().strip()
            cfg[key]["cloud"] = normalise_legacy_cloud(cfg[key]["cloud"])
            cfg[key]["auth_mode"] = self.vars[f"{key}.auth_mode"].get()
        cfg["sync"]["report_only"] = self.vars["report_only"].get()
        cfg["sync"]["no_delete"] = self.vars["no_delete"].get()
        cfg["sync"]["auto_activate"] = self.vars["auto_activate"].get()
        cfg["sync"]["sync_sensitive"] = self.vars["sync_sensitive"].get()
        cfg["sync"]["include_slow_readonly"] = self.vars["include_slow_readonly"].get()
        return cfg

    def _save_config(self):
        cfg = self._collect_config()
        config_manager.save(cfg)
        self._append_log(f"Saved config to {config_manager.CONFIG_PATH}\n")
        self._toggle_target_state()

    def _refresh_auth_fields(self):
        for key in ("tenant_a", "tenant_b"):
            if key == "tenant_b" and self.vars["report_only"].get():
                continue
            oneapi = self.vars[f"{key}.auth_mode"].get() == AUTH_MODE_ONEAPI
            for name in ("oneapi_cloud", "vanity_domain", "client_id", "client_secret", "partner_id"):
                widget = getattr(self, f"entry_{key}_{name}")
                enabled_state = "readonly" if isinstance(widget, ttk.Combobox) else "normal"
                widget.configure(state=enabled_state if oneapi else "disabled")
            for name in ("cloud", "username", "password", "api_key"):
                widget = getattr(self, f"entry_{key}_{name}")
                enabled_state = "readonly" if name == "cloud" and isinstance(widget, ttk.Combobox) else "normal"
                widget.configure(state="disabled" if oneapi else enabled_state)

    def _toggle_target_state(self):
        self._refresh_auth_fields()
        state = "disabled" if self.vars["report_only"].get() else "normal"
        for child in self.tenant_frames["tenant_b"].winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

    def _run_command(self, title, func, *args):
        self._save_config()
        cfg = config_manager.load()
        self._run_action(title, func, cfg, *args)

    def _run_action(self, title, func, *args):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_NAME, "An operation is already running.")
            return
        self._append_log(f"\n=== {title} ===\n")
        self.worker = threading.Thread(target=self._worker, args=(func, args), daemon=True)
        self.worker.start()

    def _worker(self, func, args):
        writer = QueueWriter(self.output_queue)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                func(*args)
            self.output_queue.put(("done", "Operation finished.\n"))
        except SystemExit as exc:
            self.output_queue.put(("done", f"Operation stopped with exit code {exc.code}.\n"))
        except RuntimeError as exc:
            self.output_queue.put(("log", f"{exc}\n"))
            self.output_queue.put(("done", "Operation failed.\n"))
        except Exception:
            self.output_queue.put(("log", traceback.format_exc()))
            self.output_queue.put(("done", "Operation failed.\n"))

    def _test_tenant(self, key):
        cfg = self._collect_config()
        tenant = cfg[key]
        missing = config_manager.missing_auth_fields(tenant)
        if missing:
            raise ValueError(f"{tenant.get('label') or key} is missing: {', '.join(missing)}")
        ok = config_manager.test_connection(tenant.get("label") or key, tenant)
        if not ok:
            raise RuntimeError(f"Authentication failed for {tenant.get('label') or key}.")

    def _check_authentication(self):
        self._save_config()
        cfg = self._collect_config()
        tenant_keys = ["tenant_a"] if cfg["sync"]["report_only"] else ["tenant_a", "tenant_b"]
        failures = []

        for key in tenant_keys:
            tenant = cfg[key]
            label = tenant.get("label") or key
            missing = config_manager.missing_auth_fields(tenant)
            if missing:
                failures.append(f"{label}: missing {', '.join(missing)}")
                print(f"{label}: missing {', '.join(missing)}")
                continue
            if not config_manager.test_connection(label, tenant):
                failures.append(f"{label}: authentication failed")

        if failures:
            raise RuntimeError("Authentication check failed:\n" + "\n".join(failures))
        print("\nAuthentication check passed for all configured tenant(s).")

    def _confirm_sync(self):
        if self.vars["report_only"].get():
            messagebox.showinfo(APP_NAME, "Report-only mode has no target tenant to sync.")
            return
        ok = messagebox.askyesno(
            "Apply sync",
            "This will apply source tenant changes to the target tenant. Run Dry Run first and review the report before applying.\n\nContinue?",
        )
        if ok:
            self._run_command("Apply Sync", sync.cmd_sync, True)

    def _confirm_restore(self):
        if self.vars["report_only"].get():
            messagebox.showinfo(APP_NAME, "Report-only mode has no target tenant to restore.")
            return
        backup_path = self._ask_backup_file()
        if not backup_path:
            return
        ok = messagebox.askyesno(
            "Restore backup",
            f"This will restore this backup into the configured Target tenant:\n\n{backup_path}\n\nRun Restore Preview first and review the report before applying.\n\nContinue?",
        )
        if ok:
            self._run_command("Restore Backup", sync.cmd_restore, backup_path)

    def _choose_restore_backup(self, dry_run: bool):
        if self.vars["report_only"].get():
            messagebox.showinfo(APP_NAME, "Report-only mode has no target tenant to restore.")
            return
        backup_path = self._ask_backup_file()
        if not backup_path:
            return
        if dry_run:
            self._run_command("Restore Preview", sync.cmd_restore_preview, backup_path)
        else:
            self._run_command("Restore Backup", sync.cmd_restore, backup_path)

    def _ask_backup_file(self):
        initial_dir = sync.BACKUPS_DIR if sync.BACKUPS_DIR.exists() else APP_DIR
        return filedialog.askopenfilename(
            title="Choose backup JSON to restore",
            initialdir=str(initial_dir),
            filetypes=[
                ("Backup JSON", "*.json"),
                ("All files", "*.*"),
            ],
        )

    def _open_report(self):
        for path in (sync.REPORT_FILE, sync.FULL_REPORT_FILE):
            if Path(path).exists():
                webbrowser.open(Path(path).resolve().as_uri())
                self._append_log(f"Opened {path}\n")
                return
        messagebox.showinfo(APP_NAME, "No report found yet.")

    def _open_data_folder(self):
        if sys.platform == "darwin":
            subprocess.run(["open", str(APP_DIR)], check=False)
        elif sys.platform == "win32":
            os.startfile(str(APP_DIR))
        else:
            webbrowser.open(Path(APP_DIR).resolve().as_uri())

    def _append_log(self, text):
        self.log.insert("end", text)
        self.log.see("end")

    def _drain_output(self):
        try:
            while True:
                kind, text = self.output_queue.get_nowait()
                if kind == "estimate":
                    self._append_estimate(text)
                else:
                    self._append_log(text)
        except queue.Empty:
            pass
        self.after(100, self._drain_output)

    def _append_estimate(self, text):
        current = self.estimate_text.get()
        if current.startswith("Run Backup"):
            current = ""
        compact = " ".join(line.strip(" ·") for line in text.splitlines() if line.strip())
        if compact == "▸ API call estimate":
            current = ""
        elif compact:
            current = f"{current}\n{compact}".strip()
        self.estimate_text.set(current or "Calculating estimate...")


if __name__ == "__main__":
    ZIAClonerApp().mainloop()
