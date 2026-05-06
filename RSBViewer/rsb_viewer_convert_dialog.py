#!/usr/bin/env python3
"""
rsb_viewer_convert_dialog.py — Convert-to-PNG dialog for rsb_viewer.py.

This module intentionally keeps the converter command builder beside the dialog,
so the main viewer only needs to pass in the selected .rsb file or folder.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


# ---------------------------------------------------------------------------
# Local UI colours/fonts
# Kept here so this dialog can be moved independently of the main viewer file.
# ---------------------------------------------------------------------------

DARK_BG    = "#1A1A1A"
PANEL_BG   = "#222222"
HEADER_BG  = "#2C2C2C"
ACCENT     = "#C8A96E"
ACCENT_DIM = "#7A6540"
TEXT       = "#E8E0D0"
TEXT_DIM   = "#777060"
WARNING_FG = "#E06060"

FONT_UI     = ("Consolas", 10)
FONT_BOLD   = ("Consolas", 10, "bold")
FONT_STATUS = ("Consolas", 9)


# ---------------------------------------------------------------------------
# Converter script path
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
CONVERTER_SCRIPT = SCRIPT_DIR / "rsb_to_pngsmartdetect_versioned_grouped.py"


def build_convert_command(
    target: Path,
    *,
    recursive: bool = True,
    argb8888_order: str = "bgra",
    payload_shift: int = 0,
    write_all_8888_variants: bool = False,
    group_by_format: bool = False,
    group_output_dir: str | Path | None = None,
    keep_going: bool = True,
    converter_script: Path = CONVERTER_SCRIPT,
) -> list[str]:
    """
    Build the converter subprocess command for a selected .rsb file or folder.

    The selected target is passed directly to the converter script. Directory-only
    options, such as --recursive, are only added when the target is a directory.
    """
    target = Path(target)
    cmd = [sys.executable, str(converter_script), str(target)]

    if target.is_dir() and recursive:
        cmd.append("--recursive")

    cmd += ["--argb8888-order", argb8888_order]
    cmd += ["--payload-shift", str(payload_shift)]

    if write_all_8888_variants:
        cmd.append("--write-all-8888-variants")

    if group_by_format:
        cmd.append("--group-by-format")
        if group_output_dir is not None and str(group_output_dir).strip():
            cmd += ["--group-output-dir", str(group_output_dir).strip()]

    if keep_going:
        cmd.append("--keep-going")

    return cmd


# ---------------------------------------------------------------------------
# Convert dialog
# ---------------------------------------------------------------------------

class ConvertDialog(tk.Toplevel):
    """
    Modal dialog that builds a command for rsb_to_pngsmartdetect_versioned_grouped.py
    and runs it via subprocess, streaming output into a log panel.

    target: a single .rsb Path, or a directory Path.
    """

    def __init__(self, parent: tk.Tk, target: Path) -> None:
        super().__init__(parent)
        self.title("Convert to PNG")
        self.geometry("780x580")
        self.minsize(600, 460)
        self.configure(bg=DARK_BG)
        self.resizable(True, True)
        self.grab_set()   # modal

        self._target     = target
        self._is_dir     = target.is_dir()
        self._proc: subprocess.Popen | None = None  # type: ignore[type-arg]

        self._build_styles()
        self._build_ui()

    # ------------------------------------------------------------------ styles

    def _build_styles(self) -> None:
        s = ttk.Style(self)
        # Reuse parent styles; just ensure Checkbutton looks right in this window
        s.configure("Dark.TCheckbutton",
            background=PANEL_BG, foreground=TEXT,
            font=FONT_UI,
        )
        s.map("Dark.TCheckbutton",
            background=[("active", PANEL_BG)],
            foreground=[("active", ACCENT)],
        )
        s.configure("Dark.TRadiobutton",
            background=PANEL_BG, foreground=TEXT,
            font=FONT_UI,
        )
        s.map("Dark.TRadiobutton",
            background=[("active", PANEL_BG)],
            foreground=[("active", ACCENT)],
        )
        s.configure("Dialog.TFrame",  background=PANEL_BG)
        s.configure("Dim.TLabel",     background=PANEL_BG, foreground=TEXT_DIM,   font=FONT_UI)
        s.configure("Normal.TLabel",  background=PANEL_BG, foreground=TEXT,       font=FONT_UI)
        s.configure("Section.TLabel", background=PANEL_BG, foreground=ACCENT,     font=FONT_BOLD)
        s.configure("Log.TFrame",     background=DARK_BG)

    # ------------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        # ---- Target info strip ----
        top = tk.Frame(self, bg=HEADER_BG, pady=6)
        top.pack(fill=tk.X)
        kind = "Folder" if self._is_dir else "File"
        tk.Label(top, text=f"{kind}:  {self._target}",
                 bg=HEADER_BG, fg=TEXT, font=FONT_UI,
                 anchor="w", padx=10,
                 ).pack(fill=tk.X)

        # ---- Options panel ----
        opts = tk.Frame(self, bg=PANEL_BG, pady=8)
        opts.pack(fill=tk.X, padx=0)

        # -- Row 0: ARGB8888 byte order --
        row0 = tk.Frame(opts, bg=PANEL_BG)
        row0.pack(fill=tk.X, padx=12, pady=(4, 2))
        ttk.Label(row0, text="ARGB8888 byte order:", style="Normal.TLabel",
                  ).pack(side=tk.LEFT, padx=(0, 10))
        self._order_var = tk.StringVar(value="bgra")
        for order in ("bgra", "rgba", "argb", "abgr"):
            ttk.Radiobutton(row0, text=order, variable=self._order_var,
                            value=order, style="Dark.TRadiobutton",
                            ).pack(side=tk.LEFT, padx=4)

        # -- Row 1: Payload shift --
        row1 = tk.Frame(opts, bg=PANEL_BG)
        row1.pack(fill=tk.X, padx=12, pady=2)
        ttk.Label(row1, text="Payload shift:", style="Normal.TLabel",
                  ).pack(side=tk.LEFT, padx=(0, 10))
        self._shift_var = tk.IntVar(value=0)
        for shift in (0, 1, 2, 3):
            ttk.Radiobutton(row1, text=str(shift), variable=self._shift_var,
                            value=shift, style="Dark.TRadiobutton",
                            ).pack(side=tk.LEFT, padx=4)

        # -- Row 2: Flags --
        row2 = tk.Frame(opts, bg=PANEL_BG)
        row2.pack(fill=tk.X, padx=12, pady=2)
        self._all_variants_var = tk.BooleanVar(value=False)
        self._group_var        = tk.BooleanVar(value=False)
        self._keep_going_var   = tk.BooleanVar(value=True)
        self._recursive_var    = tk.BooleanVar(value=True)

        ttk.Checkbutton(row2, text="Write all 8888 variants (16 combos)",
                        variable=self._all_variants_var,
                        style="Dark.TCheckbutton",
                        command=self._on_all_variants_toggle,
                        ).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Checkbutton(row2, text="Group by format",
                        variable=self._group_var,
                        style="Dark.TCheckbutton",
                        ).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Checkbutton(row2, text="Keep going on errors",
                        variable=self._keep_going_var,
                        style="Dark.TCheckbutton",
                        ).pack(side=tk.LEFT, padx=(0, 14))
        if self._is_dir:
            ttk.Checkbutton(row2, text="Recursive",
                            variable=self._recursive_var,
                            style="Dark.TCheckbutton",
                            ).pack(side=tk.LEFT)

        # -- Row 3: Output directory --
        row3 = tk.Frame(opts, bg=PANEL_BG)
        row3.pack(fill=tk.X, padx=12, pady=(4, 6))
        ttk.Label(row3, text="Output dir (optional):", style="Normal.TLabel",
                  ).pack(side=tk.LEFT, padx=(0, 8))
        self._outdir_var = tk.StringVar(value="")
        outdir_entry = tk.Entry(row3,
            textvariable=self._outdir_var,
            bg=DARK_BG, fg=TEXT, insertbackground=TEXT,
            font=FONT_UI, relief="flat", bd=4,
            width=36,
        )
        outdir_entry.pack(side=tk.LEFT)
        ttk.Button(row3, text="Browse", style="Accent.TButton",
                   command=self._browse_outdir,
                   ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(row3,
                  text="(leave blank to output beside source files)",
                  style="Dim.TLabel",
                  ).pack(side=tk.LEFT, padx=(10, 0))

        # -- Divider --
        tk.Frame(self, bg=HEADER_BG, height=1).pack(fill=tk.X)

        # ---- Command preview ----
        prev_frame = tk.Frame(self, bg=DARK_BG, pady=4)
        prev_frame.pack(fill=tk.X, padx=10)
        ttk.Label(prev_frame, text="Command:", style="Dim.TLabel",
                  background=DARK_BG,
                  ).pack(side=tk.LEFT, padx=(0, 6))
        self._cmd_var = tk.StringVar()
        tk.Label(prev_frame,
            textvariable=self._cmd_var,
            bg=DARK_BG, fg=ACCENT_DIM,
            font=FONT_STATUS, anchor="w",
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ---- Log panel ----
        log_frame = tk.Frame(self, bg=DARK_BG)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        self._log = tk.Text(log_frame,
            bg=DARK_BG, fg=TEXT, insertbackground=TEXT,
            font=FONT_STATUS,
            relief="flat", bd=0,
            state="disabled",
            wrap="none",
        )
        log_vsb = ttk.Scrollbar(log_frame, orient="vertical",
                                command=self._log.yview,
                                style="Vertical.TScrollbar")
        log_hsb = ttk.Scrollbar(log_frame, orient="horizontal",
                                command=self._log.xview,
                                style="Horizontal.TScrollbar")
        self._log.configure(yscrollcommand=log_vsb.set,
                            xscrollcommand=log_hsb.set)
        log_vsb.pack(side=tk.RIGHT,  fill=tk.Y)
        log_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ---- Bottom button bar ----
        btn_bar = tk.Frame(self, bg=PANEL_BG, pady=6)
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self._run_btn = ttk.Button(btn_bar, text="Run",
                                   style="Accent.TButton",
                                   command=self._run)
        self._run_btn.pack(side=tk.LEFT, padx=8)

        self._stop_btn = ttk.Button(btn_bar, text="Stop",
                                    style="Accent.TButton",
                                    command=self._stop,
                                    state="disabled")
        self._stop_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(btn_bar, text="Close",
                   style="Accent.TButton",
                   command=self._on_close,
                   ).pack(side=tk.RIGHT, padx=8)

        self._status_lbl = tk.Label(btn_bar, text="",
            bg=PANEL_BG, fg=TEXT_DIM, font=FONT_STATUS, anchor="w")
        self._status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Wire up live command preview
        for var in (self._order_var, self._shift_var, self._all_variants_var,
                    self._group_var, self._keep_going_var, self._recursive_var,
                    self._outdir_var):
            var.trace_add("write", lambda *_: self._update_preview())
        self._update_preview()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----------------------------------------------------------------- helpers

    def _browse_outdir(self) -> None:
        d = filedialog.askdirectory(title="Select output directory", parent=self)
        if d:
            self._outdir_var.set(d)

    def _build_cmd(self) -> list[str]:
        return build_convert_command(
            self._target,
            recursive=self._recursive_var.get(),
            argb8888_order=self._order_var.get(),
            payload_shift=self._shift_var.get(),
            write_all_8888_variants=self._all_variants_var.get(),
            group_by_format=self._group_var.get(),
            group_output_dir=self._outdir_var.get(),
            keep_going=self._keep_going_var.get(),
        )

    def _update_preview(self) -> None:
        cmd = self._build_cmd()
        # Show a compact version — just the args after the script name
        args_str = " ".join(cmd[2:])
        self._cmd_var.set(f"...{CONVERTER_SCRIPT.name} {args_str}")

    def _on_all_variants_toggle(self) -> None:
        """When all-variants is on, byte order and shift controls are irrelevant."""
        self._update_preview()

    def _log_write(self, text: str, tag: str = "") -> None:
        self._log.configure(state="normal")
        if tag:
            self._log.insert("end", text, tag)
        else:
            self._log.insert("end", text)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_dialog_status(self, msg: str, error: bool = False) -> None:
        self._status_lbl.configure(
            text=msg,
            fg=WARNING_FG if error else TEXT_DIM,
        )

    # ------------------------------------------------------------------- run

    def _run(self) -> None:
        if not CONVERTER_SCRIPT.exists():
            messagebox.showerror(
                "Script not found",
                f"Could not find converter script:\n{CONVERTER_SCRIPT}",
                parent=self,
            )
            return

        # Clear log
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        self._log.tag_configure("err", foreground=WARNING_FG)
        self._log.tag_configure("ok",  foreground="#80C080")
        self._log.tag_configure("dim", foreground=TEXT_DIM)

        cmd = self._build_cmd()
        self._log_write(f"$ {' '.join(cmd)}\n", "dim")

        self._run_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._set_dialog_status("Running...")

        def worker() -> None:
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                assert self._proc.stdout is not None
                for line in self._proc.stdout:
                    tag = "err" if line.startswith("ERR") else ("ok" if line.startswith("OK") else "")
                    self.after(0, self._log_write, line, tag)
                self._proc.wait()
                rc = self._proc.returncode
            except Exception as exc:
                self.after(0, self._log_write, f"\nException: {exc}\n", "err")
                rc = -1
            finally:
                self._proc = None

            def done() -> None:
                self._run_btn.configure(state="normal")
                self._stop_btn.configure(state="disabled")
                if rc == 0:
                    self._set_dialog_status("Done.")
                else:
                    self._set_dialog_status(f"Finished with errors (exit {rc}).", error=True)

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            self._log_write("\n[Stopped by user]\n", "err")
        self._stop_btn.configure(state="disabled")
        self._run_btn.configure(state="normal")
        self._set_dialog_status("Stopped.", error=True)

    def _on_close(self) -> None:
        if self._proc:
            self._proc.terminate()
        self.destroy()



