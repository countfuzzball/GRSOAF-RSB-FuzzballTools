#!/usr/bin/env python3
"""
rsb_viewer.py — GUI viewer for Red Storm .rsb files.

Requires rsb_format.py and rsb_footer.py in the same directory (or on PYTHONPATH).
"""
from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from rsb_footer import (
    find_animation_frame_records,
    find_damage_texture_record,
    parse_surface_id,
    scan_length_prefixed_strings,
    scan_plain_rsb_strings,
    try_v8_footer_map,
)
from rsb_format import RSBFile, expected_mipmap_sizes, load_rsb


# ---------------------------------------------------------------------------
# Data gathering — pure logic, no GUI
# ---------------------------------------------------------------------------

Row     = tuple[str, str]        # (field, value)
Section = tuple[str, list[Row]]  # (section_title, rows)


def gather_sections(rsb: RSBFile) -> tuple[list[Section], list[str]]:
    """
    Return (sections, warnings) from a loaded RSBFile.
    Each section is (title, [(field, value), ...]).
    warnings is a list of plain-text warning strings.
    """
    h           = rsb.header
    data        = rsb.data
    footer      = rsb.footer
    payload_end = rsb.payload_end
    warnings: list[str]     = []
    sections: list[Section] = []

    # ---- File / Header ----
    header_rows: list[Row] = [
        ("File size",        f"{len(data):,} bytes"),
        ("Version",          str(h.version)),
        ("Dimensions",       f"{h.width} x {h.height}"),
        ("Contains palette", str(bool(h.contains_palette))),
        ("Bits R/G/B/A",     f"{h.bits_red}, {h.bits_green}, {h.bits_blue}, {h.bits_alpha}"),
        ("Bit depth",        f"{h.bit_depth} byte(s)/pixel"),
        ("DXT type",         str(h.dxt_type) if h.dxt_type is not None else "n/a"),
        ("Format guess",     h.format_name),
        ("Payload start",    f"0x{h.payload_start:X}"),
    ]

    if rsb.payload_size is None:
        header_rows.append(("Payload size", "unknown / unsupported (paletted?)"))
        header_rows.append(("Footer",       "not calculated"))
    else:
        header_rows.append(("Payload size", f"{rsb.payload_size:,} bytes"))
        if payload_end is not None:
            header_rows.append(("Payload end", f"0x{payload_end:X}"))
            if payload_end > len(data):
                overshoot = payload_end - len(data)
                warnings.append(f"Payload exceeds file size by {overshoot} byte(s)")
        header_rows.append(("Footer size",      f"{len(footer)} bytes"))
        header_rows.append(("Mipmap count",     str(rsb.mipmap_count)))
        header_rows.append(("Mipmap data size", f"{len(rsb.mipmap_data):,} bytes"))
        if rsb.tiled is not None:
            header_rows.append(("Tiled", str(rsb.tiled)))

    sections.append(("File / Header", header_rows))

    # ---- Version-specific raw bytes ----
    ver_rows: list[Row] = []
    if h.version > 7:
        ver_rows.append((
            f"v{h.version} skipped 7-byte block @ 0x0C",
            data[0x0C:0x13].hex(" "),
        ))
    if h.version >= 9:
        dxt_skip = h.payload_start - 8
        ver_rows.append((
            f"v9+ unknown 4 bytes @ 0x{dxt_skip:X}",
            data[dxt_skip:dxt_skip + 4].hex(" "),
        ))
    if ver_rows:
        sections.append(("Version-specific bytes", ver_rows))

    # ---- Mipmaps ----
    if rsb.mipmap_count and payload_end is not None:
        mip_rows: list[Row] = []
        sizes     = expected_mipmap_sizes(h, rsb.mipmap_count)
        mip_start = payload_end + len(footer)
        if sizes is None:
            mip_rows.append(("Note", f"count={rsb.mipmap_count}, total={len(rsb.mipmap_data):,} bytes; size details unavailable"))
        else:
            cursor = mip_start
            for idx, (mw, mh, nbytes) in enumerate(sizes, 1):
                mip_rows.append((
                    f"Mip {idx}",
                    f"{mw}x{mh}, {nbytes:,} bytes  [0x{cursor:X}-0x{cursor+nbytes:X}]",
                ))
                cursor += nbytes
        sections.append(("Mipmap payloads", mip_rows))

    if not footer:
        return sections, warnings

    # ---- Footer field map ----
    footer_rows: list[Row] = []
    for line in try_v8_footer_map(footer, h.version):
        stripped = line.strip()
        if stripped.endswith(":"):
            footer_rows.append(("--", stripped.rstrip(":")))
        elif stripped.startswith("footer+"):
            rest = stripped[len("footer+"):]
            try:
                addr, desc = rest.split(" ", 1)
                footer_rows.append((f"+{addr}", desc))
            except ValueError:
                footer_rows.append(("", stripped))
        else:
            footer_rows.append(("", stripped))
    sections.append(("Footer field map", footer_rows))

    # ---- Damage texture ----
    dmg      = find_damage_texture_record(footer)
    dmg_rows: list[Row] = []
    if dmg:
        off, name = dmg
        dmg_rows.append(("Offset",  f"footer+0x{off:X}"))
        dmg_rows.append(("Enabled", "yes"))
        dmg_rows.append(("Texture", name))
    else:
        dmg_rows.append(("Result", "not found"))
    sections.append(("Damage texture record", dmg_rows))

    # ---- Surface ----
    surface   = parse_surface_id(footer)
    surf_rows: list[Row] = []
    if surface:
        sid, surface_name = surface
        surf_rows.append(("Surface ID",   str(sid)))
        surf_rows.append(("Surface name", surface_name))
        surf_rows.append(("Raw bytes",    footer[-4:].hex(" ")))
    else:
        surf_rows.append(("Result", "not found"))
    sections.append(("Surface setting", surf_rows))

    # ---- Animation frame refs ----
    anim_refs  = find_animation_frame_records(footer, dmg)
    anim_rows: list[Row] = []
    if anim_refs:
        for idx, (off, n, s) in enumerate(anim_refs, 1):
            anim_rows.append((f"Ref {idx:02d}", f"footer+0x{off:X}  len={n}  {s}"))
    else:
        anim_rows.append(("Result", "not found"))
    sections.append(("Animation frame .rsb refs", anim_rows))

    # ---- All length-prefixed strings ----
    lp = scan_length_prefixed_strings(footer)
    if lp:
        lp_rows: list[Row] = []
        for off, n, s in lp:
            label = "  [damage texture]" if dmg and off == dmg[0] + 1 and s == dmg[1] else ""
            lp_rows.append((f"footer+0x{off:X}", f"len={n}  {s}{label}"))
        sections.append(("All length-prefixed .rsb strings", lp_rows))

    # ---- Plain .rsb strings ----
    plain = scan_plain_rsb_strings(footer, base=(payload_end or 0))
    if plain:
        plain_rows: list[Row] = [(f"0x{off:X}", s) for off, s in plain]
        sections.append(("Plain .rsb strings in footer", plain_rows))

    return sections, warnings


# ---------------------------------------------------------------------------
# Colours & fonts
# ---------------------------------------------------------------------------

DARK_BG    = "#1A1A1A"
PANEL_BG   = "#222222"
HEADER_BG  = "#2C2C2C"
ACCENT     = "#C8A96E"   # warm amber
ACCENT_DIM = "#7A6540"
TEXT       = "#E8E0D0"
TEXT_DIM   = "#777060"
ROW_ODD    = "#242424"
ROW_EVEN   = "#1E1E1E"
WARNING_FG = "#E06060"
SEL_BG     = "#3A3020"

FONT_UI     = ("Consolas", 10)
FONT_BOLD   = ("Consolas", 10, "bold")
FONT_STATUS = ("Consolas", 9)


# ---------------------------------------------------------------------------
# Converter script path — sits next to this file
# ---------------------------------------------------------------------------

CONVERTER_SCRIPT = Path(__file__).parent / "rsb_to_pngsmartdetect_versioned_grouped.py"


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
        cmd = [sys.executable, str(CONVERTER_SCRIPT)]

        if self._is_dir:
            cmd.append(str(self._target))
            if self._recursive_var.get():
                cmd.append("--recursive")
        else:
            cmd.append(str(self._target))

        cmd += ["--argb8888-order", self._order_var.get()]
        cmd += ["--payload-shift",  str(self._shift_var.get())]

        if self._all_variants_var.get():
            cmd.append("--write-all-8888-variants")
        if self._group_var.get():
            cmd.append("--group-by-format")
            outdir = self._outdir_var.get().strip()
            if outdir:
                cmd += ["--group-output-dir", outdir]
        if self._keep_going_var.get():
            cmd.append("--keep-going")

        return cmd

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


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class RSBViewer(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("RSB Viewer")
        self.geometry("1280x760")
        self.minsize(800, 500)
        self.configure(bg=DARK_BG)

        self._node_paths: dict[str, Path] = {}
        self._selected_path: Path | None  = None   # currently selected file or dir

        self._build_styles()
        self._build_toolbar()
        self._build_statusbar()
        self._build_panes()

    # ------------------------------------------------------------------ styles

    def _build_styles(self) -> None:
        s = ttk.Style(self)
        s.theme_use("clam")

        s.configure(".",
            background=DARK_BG, foreground=TEXT,
            font=FONT_UI, borderwidth=0, relief="flat",
        )
        s.configure("Accent.TButton",
            background=ACCENT_DIM, foreground=TEXT,
            font=FONT_BOLD, padding=(10, 4),
            relief="flat", borderwidth=0,
        )
        s.map("Accent.TButton",
            background=[("active", ACCENT), ("pressed", ACCENT)],
            foreground=[("active", DARK_BG), ("pressed", DARK_BG)],
        )
        s.configure("File.Treeview",
            background=PANEL_BG, foreground=TEXT,
            fieldbackground=PANEL_BG,
            font=FONT_UI, rowheight=20,
            borderwidth=0, indent=14,
        )
        s.configure("File.Treeview.Heading",
            background=PANEL_BG, foreground=TEXT_DIM,
            font=FONT_STATUS, relief="flat",
        )
        s.map("File.Treeview",
            background=[("selected", SEL_BG)],
            foreground=[("selected", ACCENT)],
        )
        s.configure("RSB.Treeview",
            background=ROW_EVEN, foreground=TEXT,
            fieldbackground=ROW_EVEN,
            font=FONT_UI, rowheight=22,
            borderwidth=0,
        )
        s.configure("RSB.Treeview.Heading",
            background=HEADER_BG, foreground=ACCENT,
            font=FONT_BOLD, relief="flat", padding=(8, 4),
        )
        s.map("RSB.Treeview",
            background=[("selected", SEL_BG)],
            foreground=[("selected", TEXT)],
        )
        s.configure("Vertical.TScrollbar",
            background=PANEL_BG, troughcolor=DARK_BG,
            arrowcolor=TEXT_DIM, borderwidth=0, width=10,
        )
        s.configure("Horizontal.TScrollbar",
            background=PANEL_BG, troughcolor=DARK_BG,
            arrowcolor=TEXT_DIM, borderwidth=0, width=10,
        )
        s.configure("TPanedwindow", background=HEADER_BG)

    # ----------------------------------------------------------------- toolbar

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self, bg=PANEL_BG, pady=5)
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(bar, text="Open folder",
                   style="Accent.TButton",
                   command=self._open_directory,
                   ).pack(side=tk.LEFT, padx=(8, 4))

        ttk.Button(bar, text="Open file",
                   style="Accent.TButton",
                   command=self._open_file,
                   ).pack(side=tk.LEFT, padx=(0, 8))

        self._convert_btn = ttk.Button(bar, text="Convert to PNG",
                   style="Accent.TButton",
                   command=self._open_convert_dialog,
                   state="disabled",
                   )
        self._convert_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._filepath_var = tk.StringVar(value="No file loaded")
        tk.Label(bar,
            textvariable=self._filepath_var,
            bg=PANEL_BG, fg=TEXT_DIM,
            font=FONT_UI, anchor="w",
        ).pack(side=tk.LEFT, padx=(4, 0), fill=tk.X, expand=True)

    # --------------------------------------------------------------- statusbar

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self, bg=PANEL_BG, height=24)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        bar.pack_propagate(False)

        self._status_var = tk.StringVar(value="Ready.")
        self._status_lbl = tk.Label(bar,
            textvariable=self._status_var,
            bg=PANEL_BG, fg=TEXT_DIM,
            font=FONT_STATUS, anchor="w", padx=8,
        )
        self._status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

    # ------------------------------------------------------------------- panes

    def _build_panes(self) -> None:
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # ---- Left: file tree ----
        left = tk.Frame(paned, bg=PANEL_BG)

        self._file_tree = ttk.Treeview(
            left,
            columns=("name",),
            show="tree",
            style="File.Treeview",
            selectmode="browse",
        )
        self._file_tree.column("#0",   width=0,   minwidth=0,   stretch=False)
        self._file_tree.column("name", width=240, minwidth=120, stretch=True, anchor="w")

        lvsb = ttk.Scrollbar(left, orient="vertical",
                              command=self._file_tree.yview,
                              style="Vertical.TScrollbar")
        self._file_tree.configure(yscrollcommand=lvsb.set)
        self._file_tree.bind("<<TreeviewSelect>>", self._on_file_select)

        self._file_tree.tag_configure("dir",  foreground=ACCENT,     font=FONT_BOLD)
        self._file_tree.tag_configure("rsb",  foreground=TEXT)
        self._file_tree.tag_configure("warn", foreground=WARNING_FG)

        lvsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        paned.add(left, weight=0)

        # ---- Right: field view ----
        right = tk.Frame(paned, bg=DARK_BG)

        self._field_tree = ttk.Treeview(
            right,
            columns=("field", "value"),
            show="headings",
            style="RSB.Treeview",
            selectmode="browse",
        )
        self._field_tree.heading("field", text="Field", anchor="w")
        self._field_tree.heading("value", text="Value", anchor="w")
        self._field_tree.column("field", width=300, minwidth=160, stretch=False, anchor="w")
        self._field_tree.column("value", width=700, minwidth=200, stretch=True,  anchor="w")

        rvsb = ttk.Scrollbar(right, orient="vertical",
                              command=self._field_tree.yview,
                              style="Vertical.TScrollbar")
        self._field_tree.configure(yscrollcommand=rvsb.set)

        self._field_tree.tag_configure("odd",     background=ROW_ODD,   foreground=TEXT)
        self._field_tree.tag_configure("even",    background=ROW_EVEN,  foreground=TEXT)
        self._field_tree.tag_configure("section", background=HEADER_BG, foreground=ACCENT)
        self._field_tree.tag_configure("dim",     background=ROW_EVEN,  foreground=TEXT_DIM)

        rvsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._field_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        paned.add(right, weight=1)

    # ----------------------------------------------------------------- actions

    def _open_directory(self) -> None:
        d = filedialog.askdirectory(title="Open folder containing .rsb files")
        if d:
            self._populate_file_tree(Path(d))

    def _open_file(self) -> None:
        p = filedialog.askopenfilename(
            title="Open RSB file",
            filetypes=[("RSB files", "*.rsb"), ("All files", "*.*")],
        )
        if p:
            self._selected_path = Path(p)
            self._convert_btn.configure(state="normal")
            self._load(Path(p))

    def _open_convert_dialog(self) -> None:
        if self._selected_path is None:
            return
        ConvertDialog(self, self._selected_path)

    def _on_file_select(self, _event: tk.Event) -> None:  # type: ignore[type-arg]
        sel = self._file_tree.selection()
        if not sel:
            return
        path = self._node_paths.get(sel[0])
        if path is None:
            return
        self._selected_path = path
        self._convert_btn.configure(state="normal")
        if path.is_file():
            self._load(path)

    # --------------------------------------------------------------- file tree

    def _populate_file_tree(self, root: Path) -> None:
        for item in self._file_tree.get_children():
            self._file_tree.delete(item)
        self._node_paths.clear()
        self._clear_fields()
        self._filepath_var.set(str(root))
        self._selected_path = root
        self._convert_btn.configure(state="normal")

        count = self._add_directory(root, parent="", label=root.name)
        self._set_status(f"{count} .rsb file(s) found in {root}")

    def _add_directory(self, directory: Path, parent: str, label: str) -> int:
        """Recursively add a directory node and its .rsb children. Returns .rsb count."""
        iid = self._file_tree.insert(parent, "end",
            values=(f"[ {label} ]",),
            tags=("dir",),
            open=True,
        )
        self._node_paths[iid] = directory

        count = 0
        try:
            entries = sorted(directory.iterdir(),
                             key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return 0

        for entry in entries:
            if entry.is_dir():
                count += self._add_directory(entry, parent=iid, label=entry.name)
            elif entry.suffix.lower() == ".rsb":
                fiid = self._file_tree.insert(iid, "end",
                    values=(entry.name,),
                    tags=("rsb",),
                )
                self._node_paths[fiid] = entry
                count += 1

        # Prune directories that contained no .rsb files at any depth
        if count == 0:
            self._file_tree.delete(iid)

        return count

    # --------------------------------------------------------------- field view

    def _load(self, path: Path) -> None:
        self._clear_fields()
        try:
            rsb = load_rsb(path)
        except Exception as exc:
            self._filepath_var.set(str(path))
            self._set_status(f"Error loading {path.name}: {exc}", error=True)
            return

        sections, warnings = gather_sections(rsb)
        self._filepath_var.set(str(path))
        self._populate_fields(sections)

        if warnings:
            self._set_status("  !  " + "   |   ".join(warnings), error=True)
        else:
            total = sum(len(rows) for _, rows in sections)
            self._set_status(f"{total} fields across {len(sections)} sections  --  {path.name}")

    def _clear_fields(self) -> None:
        for item in self._field_tree.get_children():
            self._field_tree.delete(item)

    def _populate_fields(self, sections: list[Section]) -> None:
        row_idx = 0
        for title, rows in sections:
            self._field_tree.insert("", "end",
                values=(title, ""),
                tags=("section",),
            )
            for field, value in rows:
                is_sep = field in ("--", "")
                tag    = "dim" if is_sep else ("odd" if row_idx % 2 else "even")
                self._field_tree.insert("", "end",
                    values=(
                        f"  > {value}" if is_sep else f"  {field}",
                        ""             if is_sep else value,
                    ),
                    tags=(tag,),
                )
                row_idx += 1

    # ----------------------------------------------------------------- helpers

    def _set_status(self, msg: str, error: bool = False) -> None:
        self._status_var.set(msg)
        self._status_lbl.configure(fg=WARNING_FG if error else TEXT_DIM)


# ---------------------------------------------------------------------------

def main() -> None:
    app = RSBViewer()
    app.mainloop()


if __name__ == "__main__":
    main()
