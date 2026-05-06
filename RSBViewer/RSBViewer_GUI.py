#!/usr/bin/env python3
"""
rsb_viewer.py — GUI viewer for Red Storm .rsb files.

Requires rsb_format.py and rsb_footer.py in the same directory (or on PYTHONPATH).
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - preview still works with Tk PhotoImage where possible
    Image = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]

from rsb_footer import (
    ALPHA_TEST_FUNCTION_NAMES,
    BLEND_FUNCTION_NAMES_DST,
    BLEND_FUNCTION_NAMES_SRC,
    GAME_FLAGS,
    SCROLL_MODE_NAMES,
    SCROLL_TYPE_NAMES,
    SUBSAMPLING_NAMES,
    SURFACE_NAMES,
    find_animation_frame_records,
    find_damage_texture_record,
    parse_surface_id,
    scan_length_prefixed_strings,
    scan_plain_rsb_strings,
    try_v8_footer_map,
)
from rsb_format import RSBFile, expected_mipmap_sizes, load_rsb

try:
    from rsb_inspect import build_inspection_dict
except Exception:  # pragma: no cover - viewer can still show old read-only sections
    build_inspection_dict = None  # type: ignore[assignment]

from rsb_viewer_convert_dialog import ConvertDialog
from rsb_viewer_scrollable import ScrollableFrame


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
# Converter / writer script paths — scripts sit next to this file
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
CONVERTER_SCRIPT = SCRIPT_DIR / "rsb_to_pngsmartdetect_versioned_grouped.py"
RSB2PNG_SCRIPT = SCRIPT_DIR / "rsb2png.py"

# Preview rendering first tries a straightforward rsb2png.py, then falls back
# to the smarter grouped converter this viewer was already using.
PREVIEW_CONVERTER_CANDIDATES = (
    RSB2PNG_SCRIPT,
    CONVERTER_SCRIPT,
)

# Writer/editing script paths. Save/Save As run the PNG->RSB writer using
# the currently displayed preview PNG as input and editable metadata as flags.
PNG2RSB_SCRIPT = SCRIPT_DIR / "png2rsb.py"
PNG2RSB_WRITER_CANDIDATES = (
    SCRIPT_DIR / "png_to_rsb_v89_rsbeditor_anim_fixed.py",
    PNG2RSB_SCRIPT,
)

EDIT_STATE_SCHEMA = "rsb_viewer_experimental_edit_state_v1"

ANIMATION_TYPE_NAMES = {
    0: "disabled",
    1: "oscillate",
    2: "constant",
}

# RSBEditor's subsampling priority enum is a 0-based field:
#   0 = One, 1 = Two, 2 = Three, 3 = Never
# Keep the GUI and writer range aligned; do not expose a phantom option 4.
SUBSAMPLING_CHOICES = {
    0: SUBSAMPLING_NAMES.get(0, "One"),
    1: SUBSAMPLING_NAMES.get(1, "Two"),
    2: SUBSAMPLING_NAMES.get(2, "Three"),
    3: SUBSAMPLING_NAMES.get(3, "Never"),
}

EXPORT_FORMAT_CHOICES = ("argb8888", "rgb888", "rgb565", "argb1555", "argb4444")
EXPORT_BYTE_ORDER_CHOICES = ("argb", "rgba", "bgra")

TEXTURE_SUFFIXES = {".rsb", ".png"}


def choice_label(value: int | None, names: dict[int, str]) -> str:
    """Return a stable combobox label such as '5: Sand'."""
    if value is None:
        return ""
    return f"{value}: {names.get(value, 'unknown')}"


def choice_values(names: dict[int, str]) -> list[str]:
    return [choice_label(k, names) for k in sorted(names)]


def get_path(obj: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def field_value(fields: dict[str, Any], name: str, default: Any = None) -> Any:
    obj = fields.get(name)
    if not isinstance(obj, dict):
        return default
    return obj.get("value", default)


def field_enabled(fields: dict[str, Any], name: str, default: bool = False) -> bool:
    obj = fields.get(name)
    if not isinstance(obj, dict):
        return default
    if "enabled" in obj and obj["enabled"] is not None:
        return bool(obj["enabled"])
    if "value" in obj and obj["value"] is not None:
        return bool(obj["value"])
    return default


def adjacent_json_path(path: Path) -> Path:
    """Match rsb_inspect.py --write-json naming: texture.rsb -> texture.rsb.json."""
    return path.with_name(f"{path.name}.json")


def find_png2rsb_writer() -> Path:
    """Return the preferred PNG->RSB writer script path for command-plan output."""
    for script in PNG2RSB_WRITER_CANDIDATES:
        if script.exists():
            return script
    # Keep the command useful even before the script is copied beside the viewer.
    return PNG2RSB_WRITER_CANDIDATES[0]


def parse_choice_value(value: Any) -> int | None:
    """Extract the integer from combobox labels like '5: Sand'."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    head = text.split(":", 1)[0].strip()
    try:
        return int(head)
    except ValueError:
        return None


def boolish(value: Any) -> bool:
    """Interpret Tk values, parsed combobox values, and text values as booleans."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "off", "disabled", ""}:
            return False
        parsed = parse_choice_value(text)
        if parsed is not None:
            return parsed != 0
    return bool(value)


def intish(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return default
    parsed = parse_choice_value(text)
    if parsed is not None:
        return parsed
    return int(float(text))


def floatish(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    parsed = parse_choice_value(text)
    if parsed is not None:
        return float(parsed)
    return float(text)


def textish(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def find_preview_converter() -> Path | None:
    """Return the first available converter script suitable for preview rendering."""
    for script in PREVIEW_CONVERTER_CANDIDATES:
        if script.exists():
            return script
    return None


def choose_preview_png(outdir: Path, source_rsb: Path) -> Path | None:
    """Pick the most likely preview PNG produced for one RSB conversion."""
    pngs = [p for p in outdir.rglob("*.png") if p.is_file() and p.stat().st_size > 0]
    if not pngs:
        return None

    source_stem = source_rsb.stem.lower()

    def score(path: Path) -> tuple[int, float, int, str]:
        name = path.stem.lower()
        exact = 2 if name == source_stem else (1 if source_stem in name else 0)
        # Prefer plausible one-file preview output over accidental thumbnails,
        # but keep the newest file as a useful tie-breaker.
        return (exact, path.stat().st_mtime, path.stat().st_size, str(path))

    return max(pngs, key=score)



# ---------------------------------------------------------------------------
# Save As export options dialog
# ---------------------------------------------------------------------------

class SaveAsOptionsDialog(tk.Toplevel):
    """Minimal Save As dialog for clean RSB rebuild/export options."""

    def __init__(
        self,
        parent: tk.Tk,
        *,
        initial_path: Path,
        initial_version: int,
        initial_format: str,
        initial_byte_order: str = "argb",
    ) -> None:
        super().__init__(parent)
        self.result: dict[str, Any] | None = None
        self.title("Export clean RSB")
        self.configure(bg=DARK_BG)
        self.resizable(False, False)

        version = initial_version if initial_version in (8, 9) else 8
        fmt = initial_format.lower() if initial_format.lower() in EXPORT_FORMAT_CHOICES else "argb8888"
        byte_order = initial_byte_order.lower() if initial_byte_order.lower() in EXPORT_BYTE_ORDER_CHOICES else "argb"

        self._initial_path = initial_path
        self.path_var = tk.StringVar(value=str(initial_path))
        self.version_var = tk.StringVar(value=str(version))
        self.format_var = tk.StringVar(value=fmt.upper())
        self.byte_order_var = tk.StringVar(value=byte_order.upper())

        self._build_widgets()

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _event: self._ok())
        self.bind("<Escape>", lambda _event: self._cancel())

        self.transient(parent)
        self.grab_set()
        self.after_idle(self._path_entry.focus_set)
        self.wait_window(self)

    def _build_widgets(self) -> None:
        body = tk.Frame(self, bg=DARK_BG, padx=14, pady=14)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text="Clean rebuild target",
            bg=DARK_BG, fg=ACCENT, font=FONT_BOLD,
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        self._label(body, "Output RSB", 1)
        self._path_entry = tk.Entry(
            body,
            textvariable=self.path_var,
            bg=PANEL_BG, fg=TEXT, insertbackground=TEXT,
            font=FONT_UI, relief="flat", bd=4, width=64,
        )
        self._path_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=3)
        ttk.Button(
            body,
            text="Browse",
            style="Accent.TButton",
            command=self._browse_output,
        ).grid(row=1, column=2, sticky="ew", pady=3)

        self._label(body, "RSB version", 2)
        ttk.Combobox(
            body,
            textvariable=self.version_var,
            values=["8", "9"],
            state="readonly",
            style="Dark.TCombobox",
            font=FONT_UI,
            width=14,
        ).grid(row=2, column=1, sticky="w", padx=(0, 8), pady=3)

        self._label(body, "Pixel format", 3)
        ttk.Combobox(
            body,
            textvariable=self.format_var,
            values=[fmt.upper() for fmt in EXPORT_FORMAT_CHOICES],
            state="readonly",
            style="Dark.TCombobox",
            font=FONT_UI,
            width=14,
        ).grid(row=3, column=1, sticky="w", padx=(0, 8), pady=3)

        self._label(body, "Byte order", 4)
        ttk.Combobox(
            body,
            textvariable=self.byte_order_var,
            values=[order.upper() for order in EXPORT_BYTE_ORDER_CHOICES],
            state="readonly",
            style="Dark.TCombobox",
            font=FONT_UI,
            width=14,
        ).grid(row=4, column=1, sticky="w", padx=(0, 8), pady=3)

        tk.Label(
            body,
            text="All other RSB behaviour is pulled from the Editable metadata tab.",
            bg=DARK_BG, fg=TEXT_DIM, font=FONT_STATUS,
            anchor="w", justify="left",
        ).grid(row=5, column=1, columnspan=2, sticky="ew", pady=(8, 4))

        buttons = tk.Frame(body, bg=DARK_BG)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", style="Accent.TButton", command=self._cancel).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(buttons, text="Export", style="Accent.TButton", command=self._ok).pack(side=tk.RIGHT)

        body.grid_columnconfigure(1, weight=1)

    def _label(self, parent: tk.Widget, text: str, row: int) -> None:
        tk.Label(
            parent,
            text=text,
            bg=DARK_BG, fg=TEXT_DIM, font=FONT_UI,
            anchor="e", padx=8, pady=2,
        ).grid(row=row, column=0, sticky="e")

    def _browse_output(self) -> None:
        current_text = self.path_var.get().strip()
        current = Path(current_text) if current_text else self._initial_path
        p = filedialog.asksaveasfilename(
            parent=self,
            title="Save rebuilt RSB as",
            initialdir=str(current.parent),
            initialfile=current.name,
            defaultextension=".rsb",
            filetypes=[("RSB files", "*.rsb"), ("All files", "*.*")],
        )
        if p:
            self.path_var.set(p)

    def _ok(self) -> None:
        path_text = self.path_var.get().strip()
        if not path_text:
            messagebox.showerror("Save As", "Choose an output .rsb path.", parent=self)
            return

        output_path = Path(path_text).expanduser()
        if output_path.suffix == "":
            output_path = output_path.with_suffix(".rsb")

        try:
            version = int(self.version_var.get())
        except ValueError:
            messagebox.showerror("Save As", "RSB version must be 8 or 9.", parent=self)
            return
        if version not in (8, 9):
            messagebox.showerror("Save As", "RSB version must be 8 or 9.", parent=self)
            return

        fmt = self.format_var.get().strip().lower()
        if fmt not in EXPORT_FORMAT_CHOICES:
            messagebox.showerror("Save As", f"Unsupported pixel format: {self.format_var.get()}", parent=self)
            return

        byte_order = self.byte_order_var.get().strip().lower()
        if byte_order not in EXPORT_BYTE_ORDER_CHOICES:
            messagebox.showerror("Save As", f"Unsupported byte order: {self.byte_order_var.get()}", parent=self)
            return

        self.result = {
            "output_path": output_path,
            "version": version,
            "format": fmt,
            "byte_order": byte_order,
        }
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


# ---------------------------------------------------------------------------
# Convert dialog moved to rsb_viewer_convert_dialog.py
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class RSBViewer(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("RSB Viewer")
        self.geometry("1280x840")
        self.minsize(900, 620)
        self.configure(bg=DARK_BG)

        self._node_paths: dict[str, Path] = {}
        self._selected_path: Path | None  = None   # currently selected file or dir
        self._current_json: dict[str, Any] | None = None
        self._json_source: str | None = None
        self._current_save_path: Path | None = None
        self._current_export_options: dict[str, Any] | None = None
        self._edit_vars: dict[str, tk.Variable] = {}
        self._edit_row: int = 0
        self._animation_frames_frame: tk.Frame | None = None
        self._animation_frame_row: int = 0
        self._animation_frame_next_index: int = 1
        self._animation_frame_entries: list[dict[str, Any]] = []

        self._preview_tempdir = Path(tempfile.mkdtemp(prefix="rsb_viewer_preview_"))
        self._preview_generation = 0
        self._preview_original_image: Any = None
        self._preview_photo: Any = None
        self._preview_path: Path | None = None

        self._build_styles()
        self._build_toolbar()
        self._build_statusbar()
        self._build_panes()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)

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
        s.configure("Dark.TNotebook", background=DARK_BG, borderwidth=0)
        s.configure("Dark.TNotebook.Tab",
            background=PANEL_BG, foreground=TEXT_DIM,
            font=FONT_BOLD, padding=(10, 5),
        )
        s.map("Dark.TNotebook.Tab",
            background=[("selected", HEADER_BG), ("active", SEL_BG)],
            foreground=[("selected", ACCENT), ("active", TEXT)],
        )
        s.configure("Dark.TCombobox",
            fieldbackground=DARK_BG, background=PANEL_BG,
            foreground=PANEL_BG, arrowcolor=TEXT,
            selectbackground=SEL_BG, selectforeground=TEXT,
        )

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
                   ).pack(side=tk.LEFT, padx=(0, 4))

        self._save_btn = ttk.Button(bar, text="Save",
                   style="Accent.TButton",
                   command=self._save_metadata,
                   state="disabled",
                   )
        self._save_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._save_as_btn = ttk.Button(bar, text="Save as",
                   style="Accent.TButton",
                   command=self._save_metadata_as,
                   state="disabled",
                   )
        self._save_as_btn.pack(side=tk.LEFT, padx=(0, 8))

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
        self._file_tree.tag_configure("png",  foreground=TEXT_DIM)
        self._file_tree.tag_configure("warn", foreground=WARNING_FG)

        lvsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        paned.add(left, weight=0)

        # ---- Right: editable metadata + inspector details + preview ----
        right = tk.Frame(paned, bg=DARK_BG)
        right_split = ttk.PanedWindow(right, orient=tk.VERTICAL)
        right_split.pack(fill=tk.BOTH, expand=True)

        top_right = tk.Frame(right_split, bg=DARK_BG)
        self._tabs = ttk.Notebook(top_right, style="Dark.TNotebook")
        self._tabs.pack(fill=tk.BOTH, expand=True)

        edit_tab = tk.Frame(self._tabs, bg=DARK_BG)
        details_tab = tk.Frame(self._tabs, bg=DARK_BG)
        self._tabs.add(edit_tab, text="Editable metadata")
        self._tabs.add(details_tab, text="Inspector details")

        # Editable JSON-backed panel.
        # This is a normal Frame wrapped in a reusable scroll container.
        # Put all editable controls inside self._edit_frame as before.
        self._edit_scroll = ScrollableFrame(
            edit_tab,
            bg=DARK_BG,
            canvas_bg=DARK_BG,
            scrollbar_style="Vertical.TScrollbar",
        )
        self._edit_scroll.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._edit_frame = self._edit_scroll.inner

        # Existing human-readable/detail tree stays available as a second tab.
        self._field_tree = ttk.Treeview(
            details_tab,
            columns=("field", "value"),
            show="headings",
            style="RSB.Treeview",
            selectmode="browse",
        )
        self._field_tree.heading("field", text="Field", anchor="w")
        self._field_tree.heading("value", text="Value", anchor="w")
        self._field_tree.column("field", width=300, minwidth=160, stretch=False, anchor="w")
        self._field_tree.column("value", width=700, minwidth=200, stretch=True,  anchor="w")

        rvsb = ttk.Scrollbar(details_tab, orient="vertical",
                              command=self._field_tree.yview,
                              style="Vertical.TScrollbar")
        self._field_tree.configure(yscrollcommand=rvsb.set)

        self._field_tree.tag_configure("odd",     background=ROW_ODD,   foreground=TEXT)
        self._field_tree.tag_configure("even",    background=ROW_EVEN,  foreground=TEXT)
        self._field_tree.tag_configure("section", background=HEADER_BG, foreground=ACCENT)
        self._field_tree.tag_configure("dim",     background=ROW_EVEN,  foreground=TEXT_DIM)

        rvsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._field_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bottom preview frame. RSB load kicks off a temp PNG render here.
        preview = tk.Frame(right_split, bg=PANEL_BG)
        preview_header = tk.Frame(preview, bg=HEADER_BG, height=28)
        preview_header.pack(side=tk.TOP, fill=tk.X)
        tk.Label(preview_header,
            text="Preview",
            bg=HEADER_BG, fg=ACCENT, font=FONT_BOLD,
            anchor="w", padx=8,
        ).pack(side=tk.LEFT)
        self._preview_status_var = tk.StringVar(value="Open an .rsb or .png file to render a preview.")
        tk.Label(preview_header,
            textvariable=self._preview_status_var,
            bg=HEADER_BG, fg=TEXT_DIM, font=FONT_STATUS,
            anchor="w", padx=8,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        preview_body = tk.Frame(preview, bg=DARK_BG)
        preview_body.pack(fill=tk.BOTH, expand=True)
        self._preview_canvas = tk.Canvas(preview_body,
            bg=DARK_BG, highlightthickness=0, borderwidth=0)
        pvsb = ttk.Scrollbar(preview_body, orient="vertical",
                             command=self._preview_canvas.yview,
                             style="Vertical.TScrollbar")
        phsb = ttk.Scrollbar(preview_body, orient="horizontal",
                             command=self._preview_canvas.xview,
                             style="Horizontal.TScrollbar")
        self._preview_canvas.configure(yscrollcommand=pvsb.set,
                                       xscrollcommand=phsb.set)
        pvsb.pack(side=tk.RIGHT, fill=tk.Y)
        phsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._preview_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._preview_image_item = self._preview_canvas.create_image(12, 12, anchor="nw")
        self._preview_canvas.bind("<Configure>", lambda _event: self._render_preview_image())

        self._show_empty_edit_message()
        right_split.add(top_right, weight=4)
        right_split.add(preview, weight=1)
        paned.add(right, weight=1)

    # ----------------------------------------------------------------- actions

    def _open_directory(self) -> None:
        d = filedialog.askdirectory(title="Open folder containing .rsb / .png files")
        if d:
            self._populate_file_tree(Path(d))

    def _open_file(self) -> None:
        p = filedialog.askopenfilename(
            title="Open RSB or PNG file",
            filetypes=[("Texture files", "*.rsb *.png"), ("RSB files", "*.rsb"), ("PNG files", "*.png"), ("All files", "*.*")],
        )
        if p:
            selected = Path(p)
            self._selected_path = selected
            self._convert_btn.configure(state="normal" if selected.suffix.lower() == ".rsb" else "disabled")
            self._load(selected)

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
        self._convert_btn.configure(state="normal" if path.is_dir() or path.suffix.lower() == ".rsb" else "disabled")
        if path.is_file():
            self._load(path)

    # --------------------------------------------------------------- file tree

    def _populate_file_tree(self, root: Path) -> None:
        for item in self._file_tree.get_children():
            self._file_tree.delete(item)
        self._node_paths.clear()
        self._clear_fields()
        self._clear_preview("Select an .rsb or .png file to render a preview.")
        self._current_save_path = None
        self._current_export_options = None
        self._filepath_var.set(str(root))
        self._selected_path = root
        self._convert_btn.configure(state="normal")

        count = self._add_directory(root, parent="", label=root.name)
        self._set_status(f"{count} texture file(s) found in {root}")

    def _add_directory(self, directory: Path, parent: str, label: str) -> int:
        """Recursively add a directory node and its .rsb/.png children. Returns file count."""
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
            elif entry.suffix.lower() in TEXTURE_SUFFIXES:
                tag = "png" if entry.suffix.lower() == ".png" else "rsb"
                fiid = self._file_tree.insert(iid, "end",
                    values=(entry.name,),
                    tags=(tag,),
                )
                self._node_paths[fiid] = entry
                count += 1

        # Prune directories that contained no supported texture files at any depth.
        if count == 0:
            self._file_tree.delete(iid)

        return count

    # --------------------------------------------------------------- field view

    def _load(self, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix == ".png":
            self._load_png(path)
            return
        if suffix != ".rsb":
            self._set_status(f"Unsupported file type: {path.name}", error=True)
            return

        self._clear_fields()
        self._clear_preview("Rendering preview will begin after the RSB header loads.")
        self._current_save_path = path
        self._current_export_options = None
        try:
            rsb = load_rsb(path)
        except Exception as exc:
            self._filepath_var.set(str(path))
            self._clear_preview("Preview unavailable because the RSB failed to load.")
            self._set_status(f"Error loading {path.name}: {exc}", error=True)
            return

        sections, warnings = gather_sections(rsb)
        self._filepath_var.set(str(path))
        self._populate_fields(sections)
        self._start_preview_render(path)

        json_warning: str | None = None
        try:
            obj, source = self._load_or_build_json(path)
            self._current_json = obj
            self._json_source = source
            self._populate_edit_fields(obj, source)
        except Exception as exc:
            json_warning = f"JSON/editable metadata unavailable: {exc}"
            self._show_empty_edit_message(json_warning)

        if warnings or json_warning:
            all_warnings = list(warnings)
            if json_warning:
                all_warnings.append(json_warning)
            self._set_status("  !  " + "   |   ".join(all_warnings), error=True)
        else:
            total = sum(len(rows) for _, rows in sections)
            self._set_status(f"{total} fields across {len(sections)} sections  --  editable metadata populated from {source}")

    def _read_png_info(self, path: Path) -> dict[str, Any]:
        """Return basic PNG info without inventing any RSB metadata."""
        info: dict[str, Any] = {
            "width": "",
            "height": "",
            "mode": "",
            "has_alpha": False,
        }

        if Image is not None:
            with Image.open(path) as im:  # type: ignore[union-attr]
                info["width"], info["height"] = im.size
                info["mode"] = im.mode
                info["has_alpha"] = (
                    im.mode in {"RGBA", "LA"}
                    or (im.mode == "P" and "transparency" in im.info)
                )
                return info

        photo = tk.PhotoImage(file=str(path))
        info["width"] = int(photo.width())
        info["height"] = int(photo.height())
        info["mode"] = "PNG"
        return info

    def _blank_png_inspection_json(self, path: Path, png_info: dict[str, Any]) -> dict[str, Any]:
        """Build an inspector-shaped object with blank/default RSB metadata for a plain PNG."""
        has_alpha = bool(png_info.get("has_alpha"))
        bits_alpha = 8 if has_alpha else 0
        game_flag_bits = {flag_name: False for _bit, flag_name in GAME_FLAGS}

        fields: dict[str, Any] = {
            "alpha_blend_enabled": {"value": 0, "enabled": False},
            "alpha_test_enabled": {"value": 0, "enabled": False},
            "mipmaps_enabled": {"value": 0, "enabled": False},
            "animation_enabled": {"value": 0, "enabled": False},
            "scrolling_enabled": {"value": 0, "enabled": False},
            "tiled_enabled": {"value": 0, "enabled": False},
            "compress_on_load": {"value": 0, "enabled": False},
            "distortion_map": {"value": 0, "enabled": False},
            "game_flags": {"value": 0, "value_hex": "0x00000000", "bits": game_flag_bits},
            "source_blend_function": {"value": 0},
            "destination_blend_function": {"value": 0},
            "alpha_test_compare_function": {"value": 0},
            "alpha_test_reference": {"value": 128},
            "scrolling_type": {"value": 0},
            "horizontal_scroll_rate": {"value": 0.0},
            "vertical_scroll_rate": {"value": 0.0},
            "animation_type": {"value": 0},
            "animation_delay": {"value": 0.0},
        }

        return {
            "file": str(path),
            "file_size": path.stat().st_size,
            "source_kind": "plain_png",
            "header": {
                "version": 8,
                "width": png_info.get("width", ""),
                "height": png_info.get("height", ""),
                "format_name": "PNG source; RSB defaults",
                "bits": {"red": 8, "green": 8, "blue": 8, "alpha": bits_alpha},
                "payload_start": "",
                "payload_start_hex": "",
            },
            "payload": {
                "base_image_end": "",
                "base_image_end_hex": "",
            },
            "footer": {
                "size": 0,
                "fields": fields,
                "animation_tail": {
                    "detected": False,
                    "frame_count": 0,
                    "frames": [],
                },
                "damage_surface_tail": {
                    "damage_texture": {"enabled": False, "filename": ""},
                },
                "surface": {"value": None, "raw_hex": ""},
            },
            "mipmaps": {
                "count": 0,
                "count_source": "plain PNG default",
                "subsampling": 0,
                "data_size": 0,
                "levels": [],
            },
            "warnings": [
                "Plain PNG selected: editable fields start from blank/default RSB metadata.",
            ],
        }

    def _png_sections(self, path: Path, png_info: dict[str, Any]) -> list[Section]:
        rows: list[Row] = [
            ("File size", f"{path.stat().st_size:,} bytes"),
            ("Dimensions", f"{png_info.get('width', '')} x {png_info.get('height', '')}"),
            ("PNG mode", str(png_info.get("mode", ""))),
            ("Has alpha", str(bool(png_info.get("has_alpha")))),
            ("RSB metadata", "blank/default; no source footer exists"),
            ("Save input", "the selected PNG file itself"),
        ]
        return [("PNG source image", rows)]

    def _load_png(self, path: Path) -> None:
        self._clear_fields()
        self._clear_preview("Loading PNG preview...")
        self._filepath_var.set(str(path))
        self._current_save_path = None
        self._current_export_options = None

        try:
            png_info = self._read_png_info(path)
            sections = self._png_sections(path, png_info)
            self._populate_fields(sections)
            self._load_preview_image(path)

            obj = self._blank_png_inspection_json(path, png_info)
            source = "plain PNG defaults"
            self._current_json = obj
            self._json_source = source
            self._populate_edit_fields(obj, source)
        except Exception as exc:
            self._clear_preview("Preview unavailable because the PNG failed to load.")
            self._show_empty_edit_message(f"PNG/default metadata unavailable: {exc}")
            self._set_status(f"Error loading {path.name}: {exc}", error=True)
            return

        self._set_status(
            f"Plain PNG loaded: {path.name}  --  editable RSB metadata starts from blank/default values"
        )

    def _load_or_build_json(self, path: Path) -> tuple[dict[str, Any], str]:
        """
        Prefer an adjacent rsb_inspect --write-json file when it is present and
        newer than the RSB. Otherwise build the same JSON object directly via
        rsb_inspect.build_inspection_dict().
        """
        json_path = adjacent_json_path(path)
        if json_path.exists() and json_path.stat().st_mtime >= path.stat().st_mtime:
            obj = json.loads(json_path.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                raise ValueError(f"{json_path.name} did not contain a JSON object")

            # Save now writes a small wrapper containing the original inspection
            # JSON plus the current UI edit state. Unwrap that format when it is
            # loaded again so the viewer still sees the normal inspector object.
            if obj.get("schema") == EDIT_STATE_SCHEMA and isinstance(obj.get("inspection"), dict):
                inspection = obj["inspection"]
                if isinstance(obj.get("editable_values"), dict):
                    inspection["_saved_editable_values"] = obj["editable_values"]
                return inspection, f"saved edit-state JSON: {json_path.name}"

            return obj, f"adjacent JSON: {json_path.name}"

        if build_inspection_dict is None:
            raise RuntimeError("rsb_inspect.build_inspection_dict could not be imported")

        obj = build_inspection_dict(path, include_walk=False, include_raw_scans=False)
        return obj, "live inspector JSON"

    def _clear_fields(self) -> None:
        if hasattr(self, "_field_tree"):
            for item in self._field_tree.get_children():
                self._field_tree.delete(item)
        self._clear_edit_fields()

    def _clear_edit_fields(self) -> None:
        if not hasattr(self, "_edit_frame"):
            return
        for child in self._edit_frame.winfo_children():
            child.destroy()
        self._edit_vars.clear()
        self._edit_row = 0
        self._animation_frames_frame = None
        self._animation_frame_row = 0
        self._animation_frame_next_index = 1
        self._animation_frame_entries = []
        self._current_json = None
        self._json_source = None
        self._set_save_buttons_enabled(False)
        if hasattr(self, "_edit_scroll"):
            self._edit_scroll.scroll_to_top()
            self._edit_scroll.refresh()

    def _show_empty_edit_message(self, msg: str = "Open an .rsb or .png file to populate editable metadata.") -> None:
        self._clear_edit_fields()
        tk.Label(self._edit_frame,
            text=msg,
            bg=DARK_BG, fg=TEXT_DIM, font=FONT_UI,
            anchor="w", justify="left", padx=12, pady=12,
        ).grid(row=0, column=0, sticky="w")
        self._edit_frame.grid_columnconfigure(1, weight=1)
        if hasattr(self, "_edit_scroll"):
            self._edit_scroll.bind_mousewheel_to_children()
            self._edit_scroll.refresh()

    def _section_label(self, title: str) -> None:
        row = self._edit_row
        self._edit_row += 1
        tk.Label(self._edit_frame,
            text=title,
            bg=HEADER_BG, fg=ACCENT, font=FONT_BOLD,
            anchor="w", padx=8, pady=5,
        ).grid(row=row, column=0, columnspan=3, sticky="ew", padx=8, pady=(10, 3))

    def _readonly_row(self, label: str, value: Any) -> None:
        row = self._edit_row
        self._edit_row += 1
        tk.Label(self._edit_frame,
            text=label,
            bg=DARK_BG, fg=TEXT_DIM, font=FONT_UI,
            anchor="e", padx=8, pady=2,
        ).grid(row=row, column=0, sticky="e")
        tk.Label(self._edit_frame,
            text="" if value is None else str(value),
            bg=DARK_BG, fg=TEXT, font=FONT_UI,
            anchor="w", padx=8, pady=2,
        ).grid(row=row, column=1, columnspan=2, sticky="ew")

    def _entry_row(self, key: str, label: str, value: Any = "", width: int = 36) -> tk.StringVar:
        row = self._edit_row
        self._edit_row += 1
        var = tk.StringVar(value="" if value is None else str(value))
        self._edit_vars[key] = var
        tk.Label(self._edit_frame,
            text=label,
            bg=DARK_BG, fg=TEXT_DIM, font=FONT_UI,
            anchor="e", padx=8, pady=2,
        ).grid(row=row, column=0, sticky="e")
        ent = tk.Entry(self._edit_frame,
            textvariable=var,
            bg=PANEL_BG, fg=TEXT, insertbackground=TEXT,
            font=FONT_UI, relief="flat", bd=4,
            width=width,
        )
        ent.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=2)
        return var

    def _safe_animation_frame_index(self, value: Any, default: int) -> int:
        """Return a positive frame index, tolerating odd/stale inspector values."""
        try:
            idx = intish(value, default)
        except Exception:
            idx = default
        return idx if idx > 0 else default

    def _create_animation_frame_area(self) -> None:
        """Create the dynamic Animation frames area inside the editable form."""
        row = self._edit_row
        self._edit_row += 1

        tk.Label(self._edit_frame,
            text="Animation frames",
            bg=DARK_BG, fg=TEXT_DIM, font=FONT_UI,
            anchor="ne", padx=8, pady=4,
        ).grid(row=row, column=0, sticky="ne")

        outer = tk.Frame(self._edit_frame, bg=DARK_BG)
        outer.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=(2, 4))
        outer.grid_columnconfigure(0, weight=1)

        self._animation_frames_frame = tk.Frame(outer, bg=DARK_BG)
        self._animation_frames_frame.grid(row=0, column=0, sticky="ew")
        self._animation_frames_frame.grid_columnconfigure(1, weight=1)

        btn_row = tk.Frame(outer, bg=DARK_BG)
        btn_row.grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Button(btn_row,
            text="Add animation frame",
            style="Accent.TButton",
            command=self._add_blank_animation_frame,
        ).pack(side=tk.LEFT)
        tk.Label(btn_row,
            text="Adds one more --animation-frame value when Save / Save as runs the writer.",
            bg=DARK_BG, fg=TEXT_DIM, font=FONT_STATUS,
            anchor="w", padx=8,
        ).pack(side=tk.LEFT)

    def _add_animation_frame_entry(self, value: Any = "", index: int | None = None) -> tk.StringVar:
        """Add one editable animation frame filename field with a delete button."""
        if index is None:
            index = self._animation_frame_next_index
        else:
            index = self._safe_animation_frame_index(index, self._animation_frame_next_index)

        if self._animation_frames_frame is None:
            # Fallback for unexpected call order. Normal population uses the
            # dynamic frame area so added rows stay grouped together.
            while f"animation_frame.{index}" in self._edit_vars:
                index += 1
            self._animation_frame_next_index = max(self._animation_frame_next_index, index + 1)
            return self._entry_row(f"animation_frame.{index}", f"Frame {index}", value, width=48)

        row = self._animation_frame_row
        self._animation_frame_row += 1
        key = f"animation_frame.{index}"
        var = tk.StringVar(value="" if value is None else str(value))

        row_frame = tk.Frame(self._animation_frames_frame, bg=DARK_BG)
        row_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=1)
        row_frame.grid_columnconfigure(1, weight=1)

        label_widget = tk.Label(row_frame,
            text=f"Frame {index}",
            bg=DARK_BG, fg=TEXT_DIM, font=FONT_UI,
            anchor="e", padx=8, pady=2,
        )
        label_widget.grid(row=0, column=0, sticky="e")

        ent = tk.Entry(row_frame,
            textvariable=var,
            bg=PANEL_BG, fg=TEXT, insertbackground=TEXT,
            font=FONT_UI, relief="flat", bd=4,
            width=48,
        )
        ent.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=2)

        record: dict[str, Any] = {
            "key": key,
            "var": var,
            "row": row_frame,
            "label": label_widget,
        }
        del_btn = ttk.Button(row_frame,
            text="Delete",
            style="Accent.TButton",
            command=lambda rec=record: self._delete_animation_frame_entry(rec),
        )
        del_btn.grid(row=0, column=2, sticky="e", padx=(0, 2), pady=2)
        record["delete_button"] = del_btn

        self._animation_frame_entries.append(record)
        self._renumber_animation_frame_entries()

        if hasattr(self, "_edit_scroll"):
            self.after_idle(self._refresh_edit_scroll_bindings)
        return var

    def _delete_animation_frame_entry(self, record: dict[str, Any]) -> None:
        """Remove one animation frame row and keep the frame array contiguous."""
        key = str(record.get("key", ""))
        if key:
            self._edit_vars.pop(key, None)

        row_widget = record.get("row")
        if isinstance(row_widget, tk.Widget):
            row_widget.destroy()

        self._animation_frame_entries = [
            entry for entry in self._animation_frame_entries
            if entry is not record and entry.get("row") is not row_widget
        ]
        self._renumber_animation_frame_entries()
        self._refresh_edit_scroll_bindings()

    def _renumber_animation_frame_entries(self) -> None:
        """Keep visible Frame N labels and _edit_vars animation_frame.N keys in sync."""
        # Remove stale animation frame keys first so deleted rows cannot be saved.
        for key in list(self._edit_vars):
            if key.startswith("animation_frame."):
                self._edit_vars.pop(key, None)

        for idx, record in enumerate(self._animation_frame_entries, 1):
            key = f"animation_frame.{idx}"
            record["key"] = key
            var = record.get("var")
            if isinstance(var, tk.Variable):
                self._edit_vars[key] = var

            label = record.get("label")
            if isinstance(label, tk.Label):
                label.configure(text=f"Frame {idx}")

            row_widget = record.get("row")
            if isinstance(row_widget, tk.Widget):
                row_widget.grid_configure(row=idx - 1)

        self._animation_frame_row = len(self._animation_frame_entries)
        self._animation_frame_next_index = len(self._animation_frame_entries) + 1

    def _add_blank_animation_frame(self) -> None:
        """Button callback: add a blank animation frame field and enable animation."""
        enabled_var = self._edit_vars.get("animation_enabled")
        if enabled_var is not None:
            try:
                enabled_var.set(True)
            except Exception:
                pass
        self._add_animation_frame_entry("")
        self._refresh_edit_scroll_bindings()

    def _refresh_edit_scroll_bindings(self) -> None:
        """Refresh scroll region and mousewheel bindings after dynamic row changes."""
        if hasattr(self, "_edit_scroll"):
            self._edit_scroll.bind_mousewheel_to_children()
            self._edit_scroll.refresh()

    def _combo_row(self, key: str, label: str, value: str, values: list[str]) -> tk.StringVar:
        row = self._edit_row
        self._edit_row += 1
        var = tk.StringVar(value=value)
        self._edit_vars[key] = var
        tk.Label(self._edit_frame,
            text=label,
            bg=DARK_BG, fg=TEXT_DIM, font=FONT_UI,
            anchor="e", padx=8, pady=2,
        ).grid(row=row, column=0, sticky="e")
        combo = ttk.Combobox(self._edit_frame,
            textvariable=var,
            values=values,
            state="readonly",
            style="Dark.TCombobox",
            font=FONT_UI,
        )
        combo.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=2)
        return var

    def _bool_row(self, key: str, label: str, value: bool | None) -> tk.BooleanVar:
        row = self._edit_row
        self._edit_row += 1
        var = tk.BooleanVar(value=bool(value))
        self._edit_vars[key] = var
        tk.Label(self._edit_frame,
            text=label,
            bg=DARK_BG, fg=TEXT_DIM, font=FONT_UI,
            anchor="e", padx=8, pady=2,
        ).grid(row=row, column=0, sticky="e")
        cb = tk.Checkbutton(self._edit_frame,
            variable=var,
            bg=DARK_BG, fg=TEXT, activebackground=DARK_BG,
            activeforeground=ACCENT, selectcolor=PANEL_BG,
            font=FONT_UI, text="enabled",
        )
        cb.grid(row=row, column=1, sticky="w", padx=(0, 8), pady=2)
        return var

    def _field_note(self, text: str) -> None:
        row = self._edit_row
        self._edit_row += 1
        tk.Label(self._edit_frame,
            text=text,
            bg=DARK_BG, fg=TEXT_DIM, font=FONT_STATUS,
            anchor="w", justify="left", padx=8, pady=3,
        ).grid(row=row, column=1, columnspan=2, sticky="ew")

    def _populate_edit_fields(self, obj: dict[str, Any], source: str) -> None:
        self._clear_edit_fields()
        self._current_json = obj
        self._json_source = source
        self._edit_frame.grid_columnconfigure(1, weight=1)

        header = obj.get("header", {}) if isinstance(obj.get("header"), dict) else {}
        payload = obj.get("payload", {}) if isinstance(obj.get("payload"), dict) else {}
        footer = obj.get("footer", {}) if isinstance(obj.get("footer"), dict) else {}
        fields = footer.get("fields", {}) if isinstance(footer.get("fields"), dict) else {}
        mipmaps = obj.get("mipmaps", {}) if isinstance(obj.get("mipmaps"), dict) else {}
        animation_tail = footer.get("animation_tail", {}) if isinstance(footer.get("animation_tail"), dict) else {}
        damage_tail = footer.get("damage_surface_tail", {}) if isinstance(footer.get("damage_surface_tail"), dict) else {}
        damage_texture = damage_tail.get("damage_texture", {}) if isinstance(damage_tail.get("damage_texture"), dict) else {}
        surface = footer.get("surface", {}) if isinstance(footer.get("surface"), dict) else {}
        saved_editable_values = obj.get("_saved_editable_values")

        bits = header.get("bits", {}) if isinstance(header.get("bits"), dict) else {}

        self._section_label("Source / read-only image info")
        self._readonly_row("JSON source", source)
        self._readonly_row("File", obj.get("file", ""))
        self._readonly_row("File size", obj.get("file_size", ""))
        self._readonly_row("Version", header.get("version"))
        self._readonly_row("Dimensions", f"{header.get('width', '')} x {header.get('height', '')}")
        self._readonly_row("Format", header.get("format_name"))
        self._readonly_row("Bits R/G/B/A", f"{bits.get('red', '')}, {bits.get('green', '')}, {bits.get('blue', '')}, {bits.get('alpha', '')}")
        self._readonly_row("Payload start", header.get("payload_start_hex", header.get("payload_start")))
        self._readonly_row("Payload end", payload.get("base_image_end_hex", payload.get("base_image_end")))
        self._readonly_row("Footer size", footer.get("size"))

        self._section_label("Core footer flags")
        self._bool_row("alpha_blend_enabled", "Alpha blend", field_enabled(fields, "alpha_blend_enabled"))
        self._bool_row("alpha_test_enabled", "Alpha test", field_enabled(fields, "alpha_test_enabled"))
        self._bool_row("mipmaps_enabled", "Mipmaps", field_enabled(fields, "mipmaps_enabled"))
        self._bool_row("animation_enabled", "Animation", field_enabled(fields, "animation_enabled"))
        self._combo_row("scrolling_enabled", "Scrolling enabled", choice_label(field_value(fields, "scrolling_enabled"), SCROLL_MODE_NAMES), choice_values(SCROLL_MODE_NAMES))
        self._bool_row("tiled_enabled", "Tiled", field_enabled(fields, "tiled_enabled"))
        self._bool_row("compress_on_load", "Compress on load", field_enabled(fields, "compress_on_load"))
        self._bool_row("distortion_map", "Distortion map", field_enabled(fields, "distortion_map"))

        self._section_label("Game flags")
        game_flags = fields.get("game_flags", {}) if isinstance(fields.get("game_flags"), dict) else {}
        bits_obj = game_flags.get("bits", {}) if isinstance(game_flags.get("bits"), dict) else {}
        for _bit, flag_name in GAME_FLAGS:
            self._bool_row(f"game_flag.{flag_name}", flag_name, bits_obj.get(flag_name, False))
        self._readonly_row("Raw game flags", game_flags.get("value_hex", game_flags.get("value")))

        self._section_label("Alpha / blending")
        self._combo_row("source_blend_function", "Source blend", choice_label(field_value(fields, "source_blend_function"), BLEND_FUNCTION_NAMES_SRC), choice_values(BLEND_FUNCTION_NAMES_SRC))
        self._combo_row("destination_blend_function", "Destination blend", choice_label(field_value(fields, "destination_blend_function"), BLEND_FUNCTION_NAMES_DST), choice_values(BLEND_FUNCTION_NAMES_DST))
        self._combo_row("alpha_test_compare_function", "Alpha compare", choice_label(field_value(fields, "alpha_test_compare_function"), ALPHA_TEST_FUNCTION_NAMES), choice_values(ALPHA_TEST_FUNCTION_NAMES))
        self._entry_row("alpha_test_reference", "Alpha reference", field_value(fields, "alpha_test_reference", ""), width=8)

        self._section_label("Scrolling / animation")
        self._combo_row("scrolling_type", "Scrolling type", choice_label(field_value(fields, "scrolling_type"), SCROLL_TYPE_NAMES), choice_values(SCROLL_TYPE_NAMES))
        if "rotation_rate" in fields:
            self._entry_row("rotation_rate", "Rotation rate", get_path(fields, "rotation_rate", "value", default=""), width=12)
            self._entry_row("secondary_unused_rate", "Secondary/unused rate", get_path(fields, "secondary_unused_rate", "value", default=""), width=12)
        else:
            self._entry_row("horizontal_scroll_rate", "Horizontal scroll rate", get_path(fields, "horizontal_scroll_rate", "value", default=""), width=12)
            self._entry_row("vertical_scroll_rate", "Vertical scroll rate", get_path(fields, "vertical_scroll_rate", "value", default=""), width=12)
        self._combo_row("animation_type", "Animation type", choice_label(field_value(fields, "animation_type"), ANIMATION_TYPE_NAMES), choice_values(ANIMATION_TYPE_NAMES))
        self._entry_row("animation_delay", "Animation delay", get_path(fields, "animation_delay", "value", default=""), width=12)

        if animation_tail.get("detected"):
            self._readonly_row("Animation tail", "detected")
            self._readonly_row("Frame count", animation_tail.get("frame_count"))
        else:
            self._readonly_row("Animation tail", "not detected")

        self._create_animation_frame_area()
        frames = animation_tail.get("frames", [])
        if isinstance(frames, list):
            for frame in frames:
                if not isinstance(frame, dict):
                    continue
                idx = self._safe_animation_frame_index(frame.get("index"), self._animation_frame_next_index)
                self._add_animation_frame_entry(frame.get("filename", ""), index=idx)

        self._section_label("Mipmaps / subsampling")
        resolved_mip_count = mipmaps.get("count")
        if animation_tail.get("detected"):
            resolved_mip_count = get_path(animation_tail, "mipmap_count", "value", default=resolved_mip_count)
        self._entry_row("mipmap_count", "Mipmap count", resolved_mip_count if resolved_mip_count is not None else "", width=8)
        self._readonly_row("Mipmap count source", mipmaps.get("count_source"))
        resolved_subsampling = mipmaps.get("subsampling")
        if animation_tail.get("detected"):
            resolved_subsampling = get_path(animation_tail, "subsampling", "value", default=resolved_subsampling)
        self._combo_row("subsampling", "Subsampling", choice_label(resolved_subsampling, SUBSAMPLING_CHOICES), choice_values(SUBSAMPLING_CHOICES))
        self._readonly_row("Mipmap payload bytes", mipmaps.get("data_size"))
        levels = mipmaps.get("levels", [])
        if isinstance(levels, list) and levels:
            self._readonly_row("Mipmap levels", len(levels))
            for level in levels:
                if isinstance(level, dict):
                    self._readonly_row(
                        f"Mip {level.get('index')}",
                        f"{level.get('width')}x{level.get('height')}, {level.get('size')} bytes, {level.get('start_hex')}-{level.get('end_hex')}",
                    )

        self._section_label("Damage / surface")
        self._bool_row("damage_texture_enabled", "Damage texture", damage_texture.get("enabled", False))
        self._entry_row("damage_texture_filename", "Damage texture filename", damage_texture.get("filename", "") or "", width=48)
        self._combo_row("surface", "Surface", choice_label(surface.get("value"), SURFACE_NAMES), choice_values(SURFACE_NAMES))
        self._readonly_row("Surface raw", surface.get("raw_hex"))

        warnings = obj.get("warnings", [])
        if warnings:
            self._section_label("Warnings")
            if isinstance(warnings, list):
                for warning in warnings:
                    self._readonly_row("Warning", warning)
            else:
                self._readonly_row("Warning", warnings)

        self._section_label("Current editable values")
        if isinstance(saved_editable_values, dict):
            self._apply_editable_values(saved_editable_values)
            self._field_note("Restored previously saved experimental edit-state values from the sidecar JSON.")
        self._field_note("Save runs the PNG->RSB writer using the selected PNG/current preview PNG and these editable metadata values.")
        self._set_save_buttons_enabled(True)
        if hasattr(self, "_edit_scroll"):
            self._edit_scroll.bind_mousewheel_to_children()
            self._edit_scroll.refresh()

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

    # ------------------------------------------------------------ save helpers

    def _set_save_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        if hasattr(self, "_save_btn"):
            self._save_btn.configure(state=state)
        if hasattr(self, "_save_as_btn"):
            self._save_as_btn.configure(state=state)

    def _collect_edit_values(self) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        parsed: dict[str, Any] = {}
        for key, var in self._edit_vars.items():
            try:
                value = var.get()
            except Exception:
                continue
            raw[key] = value
            if isinstance(value, str):
                parsed_choice = parse_choice_value(value)
                parsed[key] = parsed_choice if parsed_choice is not None and ":" in value else value
            else:
                parsed[key] = value
        return {"raw": raw, "parsed": parsed}

    def _apply_editable_values(self, values: dict[str, Any]) -> None:
        raw = values.get("raw") if isinstance(values.get("raw"), dict) else values
        if not isinstance(raw, dict):
            return
        for key, value in raw.items():
            var = self._edit_vars.get(str(key))
            if var is None:
                continue
            try:
                var.set(value)
            except Exception:
                # A stale sidecar should not break the viewer.
                pass

    def _writer_format_from_current_json(self) -> tuple[str, list[str]]:
        """Infer png_to_rsb.py's --format value from the inspector header."""
        warnings: list[str] = []
        header = self._current_json.get("header", {}) if isinstance(self._current_json, dict) else {}
        bits = header.get("bits", {}) if isinstance(header.get("bits"), dict) else {}

        bit_tuple = (
            intish(bits.get("red"), -1),
            intish(bits.get("green"), -1),
            intish(bits.get("blue"), -1),
            intish(bits.get("alpha"), -1),
        )
        by_bits = {
            (8, 8, 8, 8): "argb8888",
            (8, 8, 8, 0): "rgb888",
            (5, 6, 5, 0): "rgb565",
            (5, 5, 5, 1): "argb1555",
            (4, 4, 4, 4): "argb4444",
        }
        if bit_tuple in by_bits:
            return by_bits[bit_tuple], warnings

        name = textish(header.get("format_name")).lower()
        squashed = "".join(ch for ch in name if ch.isalnum())
        by_name = {
            "argb8888": "argb8888",
            "a8r8g8b8": "argb8888",
            "rgba8888": "argb8888",
            "rgb888": "rgb888",
            "r8g8b8": "rgb888",
            "rgb565": "rgb565",
            "r5g6b5": "rgb565",
            "argb1555": "argb1555",
            "a1r5g5b5": "argb1555",
            "argb4444": "argb4444",
            "a4r4g4b4": "argb4444",
        }
        if squashed in by_name:
            return by_name[squashed], warnings

        warnings.append(f"Could not infer writer format from header; defaulted to argb8888. Header format was {name!r}.")
        return "argb8888", warnings

    def _game_flag_cli_name(self, flag_name: str) -> str | None:
        """Map viewer GAME_FLAGS labels to png_to_rsb.py --game-flag names."""
        key = "".join(ch for ch in flag_name.lower() if ch.isalnum())
        if "gun" in key or "bullet" in key:
            return "gunshot"
        if "grenade" in key or "explosion" in key:
            return "grenade"
        if "los" in key:
            return "los"
        if "foliage" in key:
            return "foliage"
        if "water" in key:
            return "water"
        return None

    def _build_png2rsb_command(
        self,
        input_png: Path,
        output_rsb: Path,
        export_options: dict[str, Any] | None = None,
    ) -> tuple[list[str], list[str]]:
        """
        Convert the currently selected editable metadata form values into a
        png_to_rsb.py-compatible command list using real input/output paths.

        export_options is used by Save As / clean export for the structural
        output choices: version, pixel format, and byte order. All behavioural
        footer settings still come from the editable metadata widgets.
        """
        if self._current_json is None:
            raise RuntimeError("No editable metadata is loaded")

        edit_state = self._collect_edit_values()
        values = edit_state.get("parsed", {}) if isinstance(edit_state.get("parsed"), dict) else {}
        raw_values = edit_state.get("raw", {}) if isinstance(edit_state.get("raw"), dict) else {}
        header = self._current_json.get("header", {}) if isinstance(self._current_json.get("header"), dict) else {}

        warnings: list[str] = []
        export_options = export_options or {}
        writer = find_png2rsb_writer()
        command: list[str] = [sys.executable, str(writer), str(input_png), str(output_rsb)]

        if "version" in export_options:
            version = intish(export_options.get("version"), 8)
            if version not in (8, 9):
                warnings.append(f"Unsupported Save As version {version}; command uses version 8 instead.")
                version = 8
        else:
            version = intish(header.get("version"), 8)
            if version not in (8, 9):
                warnings.append(f"png_to_rsb writer only supports V8/V9; source version {version} was changed to 8.")
                version = 8
        command += ["--version", str(version)]

        if "format" in export_options:
            fmt = textish(export_options.get("format"), "argb8888").lower()
            if fmt not in EXPORT_FORMAT_CHOICES:
                warnings.append(f"Unsupported Save As pixel format {fmt!r}; command uses argb8888 instead.")
                fmt = "argb8888"
        else:
            fmt, fmt_warnings = self._writer_format_from_current_json()
            warnings.extend(fmt_warnings)
        command += ["--format", fmt]

        byte_order = textish(export_options.get("byte_order"), "argb").lower()
        if byte_order not in EXPORT_BYTE_ORDER_CHOICES:
            warnings.append(f"Unsupported Save As byte order {byte_order!r}; command uses argb instead.")
            byte_order = "argb"
        command += ["--byte-order", byte_order]

        if version == 9:
            # The current writer only emits raw/uncompressed payloads.
            command += ["--v9-unknown", "-1", "--dxt-type", "-1"]

        if boolish(values.get("alpha_blend_enabled")):
            command.append("--alpha-blend")
        command += ["--src-blend", str(intish(values.get("source_blend_function"), 0))]
        command += ["--dst-blend", str(intish(values.get("destination_blend_function"), 0))]

        if boolish(values.get("alpha_test_enabled")):
            command.append("--alpha-test")
        command += ["--alpha-compare", str(intish(values.get("alpha_test_compare_function"), 0))]
        command += ["--alpha-ref", str(intish(values.get("alpha_test_reference"), 128))]

        enabled_game_flags: list[str] = []
        for key, value in sorted(values.items()):
            if not key.startswith("game_flag.") or not boolish(value):
                continue
            label = key.split(".", 1)[1]
            cli_name = self._game_flag_cli_name(label)
            if cli_name is None:
                warnings.append(f"Could not map game flag label {label!r} to a png_to_rsb --game-flag value.")
                continue
            enabled_game_flags.append(cli_name)
        if enabled_game_flags:
            # The writer accepts either repeatable flags or one comma-separated value.
            command += ["--game-flag", ",".join(sorted(set(enabled_game_flags)))]

        if boolish(values.get("tiled_enabled")):
            command.append("--tiled")
        if boolish(values.get("compress_on_load")):
            command.append("--compress-on-load")
        if boolish(values.get("distortion_map")):
            command.append("--distortion-map")

        subsampling = intish(values.get("subsampling"), 0)
        if subsampling not in (0, 1, 2, 3):
            warnings.append(
                f"Subsampling {subsampling} is present in the GUI, but the uploaded writer argparse currently accepts only 0, 1, 2, 3. "
                "The command will use --subsampling 0 instead."
            )
            subsampling = 0
        command += ["--subsampling", str(subsampling)]

        surface = intish(values.get("surface"), -1)
        command += ["--surface", str(surface)]

        if boolish(values.get("damage_texture_enabled")):
            damage_name = textish(values.get("damage_texture_filename") or raw_values.get("damage_texture_filename"))
            if damage_name:
                command += ["--damage-texture", damage_name]
            else:
                warnings.append("Damage texture is enabled in the GUI, but the filename is empty; --damage-texture was omitted.")

        command += ["--mipmap-count", str(intish(values.get("mipmap_count"), 0))]

        if boolish(values.get("scrolling_enabled")):
            command.append("--scroll-enabled")
        scroll_type_value = intish(values.get("scrolling_type"), 0)
        scroll_type = "rotate" if scroll_type_value == 1 else "hv"
        command += ["--scroll-type", scroll_type]

        # The inspector may expose either h/v names or rotation/secondary names
        # depending on what it detected in the original footer.
        primary = values.get("horizontal_scroll_rate", values.get("rotation_rate", 0.0))
        secondary = values.get("vertical_scroll_rate", values.get("secondary_unused_rate", 0.0))
        command += ["--scroll-primary", str(floatish(primary, 0.0))]
        command += ["--scroll-secondary", str(floatish(secondary, 0.0))]

        frame_keys = sorted(
            (key for key in values if key.startswith("animation_frame.")),
            key=lambda key: self._safe_animation_frame_index(key.split(".", 1)[1], 0),
        )
        frame_names: list[str] = []
        for key in frame_keys:
            frame_name = textish(values.get(key) or raw_values.get(key))
            if frame_name:
                frame_names.append(frame_name)

        animation_enabled = boolish(values.get("animation_enabled"))
        if frame_names and not animation_enabled:
            animation_enabled = True
            warnings.append("Animation frame filenames were provided, so --animation-enabled was added automatically.")
        if animation_enabled:
            command.append("--animation-enabled")

        anim_type_value = intish(values.get("animation_type"), 0)
        anim_type = {0: "none", 1: "oscillate", 2: "constant"}.get(anim_type_value, "none")
        if anim_type_value not in (0, 1, 2):
            warnings.append(f"Unknown animation type {anim_type_value}; command uses --animation-type none.")
        command += ["--animation-type", anim_type]
        command += ["--animation-delay", str(floatish(values.get("animation_delay"), 0.0))]

        for frame_name in frame_names:
            command += ["--animation-frame", frame_name]

        return command, warnings

    def _resolve_preview_png_for_save(self) -> Path:
        """Return the PNG that should be passed into the PNG->RSB writer."""
        if self._selected_path is not None and self._selected_path.suffix.lower() == ".png":
            if not self._selected_path.exists():
                raise RuntimeError(f"The selected PNG no longer exists: {self._selected_path}")
            return self._selected_path

        if self._preview_path is None:
            raise RuntimeError("No preview PNG is available yet. Select an RSB/PNG and let the preview load first.")
        if not self._preview_path.exists():
            raise RuntimeError(f"The current preview PNG no longer exists: {self._preview_path}")
        return self._preview_path

    def _save_metadata(self) -> None:
        """Save by rebuilding the current output RSB from the displayed/selected PNG."""
        if self._current_json is None:
            self._set_status("Nothing to save: no editable metadata is loaded.", error=True)
            return

        # A plain PNG has no existing RSB target. Treat Save like Save As so
        # the user never accidentally overwrites the source PNG with RSB bytes.
        if self._selected_path is not None and self._selected_path.suffix.lower() == ".png":
            self._save_metadata_as()
            return

        if self._current_save_path is None:
            if self._selected_path is not None and self._selected_path.is_file():
                self._current_save_path = self._selected_path
            else:
                self._save_metadata_as()
                return
        self._write_rsb_from_preview(self._current_save_path, self._current_export_options)

    def _save_metadata_as(self) -> None:
        """Choose clean export options and rebuild from the displayed preview PNG."""
        if self._current_json is None:
            self._set_status("Nothing to save: no editable metadata is loaded.", error=True)
            return

        initial_path = Path("edited.rsb")
        plain_png_selected = self._selected_path is not None and self._selected_path.suffix.lower() == ".png"
        if self._selected_path is not None:
            initial_dir = self._selected_path.parent if self._selected_path.is_file() else self._selected_path
            initial_name = "edited.rsb"
            if self._selected_path.is_file():
                initial_name = f"{self._selected_path.stem}.rsb" if plain_png_selected else f"{self._selected_path.stem}_edited.rsb"
            initial_path = initial_dir / initial_name

        header = self._current_json.get("header", {}) if isinstance(self._current_json.get("header"), dict) else {}
        initial_version = intish(header.get("version"), 8)
        if initial_version not in (8, 9):
            initial_version = 8

        initial_format, _fmt_warnings = self._writer_format_from_current_json()
        initial_byte_order = "argb"
        if isinstance(self._current_export_options, dict):
            initial_version = intish(self._current_export_options.get("version"), initial_version)
            initial_format = textish(self._current_export_options.get("format"), initial_format)
            initial_byte_order = textish(self._current_export_options.get("byte_order"), initial_byte_order)
            if self._current_save_path is not None and not plain_png_selected:
                initial_path = self._current_save_path

        dialog = SaveAsOptionsDialog(
            self,
            initial_path=initial_path,
            initial_version=initial_version,
            initial_format=initial_format,
            initial_byte_order=initial_byte_order,
        )
        if dialog.result is None:
            return

        self._current_save_path = Path(dialog.result["output_path"])
        self._current_export_options = {
            "version": dialog.result["version"],
            "format": dialog.result["format"],
            "byte_order": dialog.result["byte_order"],
        }
        self._write_rsb_from_preview(self._current_save_path, self._current_export_options)

    def _write_rsb_from_preview(self, output_path: Path, export_options: dict[str, Any] | None = None) -> None:
        """
        Run png_to_rsb using the selected PNG or currently displayed preview PNG as input.

        The writer is run against a temporary output in the destination folder;
        the final file is replaced only after the writer exits successfully.
        """
        try:
            input_png = self._resolve_preview_png_for_save()
            writer = find_png2rsb_writer()
            if not writer.exists():
                raise RuntimeError(f"PNG->RSB writer script not found: {writer}")

            output_path = output_path.expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with tempfile.NamedTemporaryFile(
                prefix=f".{output_path.stem}.",
                suffix=".rsb.tmp",
                dir=str(output_path.parent),
                delete=False,
            ) as tmp:
                temp_output = Path(tmp.name)

            command, warnings = self._build_png2rsb_command(input_png, temp_output, export_options=export_options)
        except Exception as exc:
            self._set_status(f"Save failed: {exc}", error=True)
            messagebox.showerror("Save failed", str(exc), parent=self)
            return

        self._set_save_buttons_enabled(False)
        option_suffix = ""
        if isinstance(export_options, dict):
            option_suffix = (
                f" [{export_options.get('version')}/"
                f"{str(export_options.get('format', '')).upper()}/"
                f"{str(export_options.get('byte_order', '')).upper()}]"
            )
        self._set_status(f"Running PNG->RSB writer for {output_path.name}{option_suffix}...")

        def worker() -> None:
            rc = -1
            output = ""
            error_message = ""
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(SCRIPT_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                rc = completed.returncode
                output = completed.stdout.strip()
                if rc == 0:
                    temp_output.replace(output_path)
                else:
                    error_message = output or f"writer exited with status {rc}"
                    try:
                        temp_output.unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception as exc:
                error_message = str(exc)
                try:
                    temp_output.unlink(missing_ok=True)
                except Exception:
                    pass

            def done() -> None:
                self._set_save_buttons_enabled(True)
                if rc == 0:
                    warn_msg = ""
                    if warnings:
                        warn_msg = "  Warnings: " + " | ".join(warnings)
                    self._set_status(f"Saved rebuilt RSB: {output_path}{warn_msg}", error=bool(warnings))
                    if warnings:
                        messagebox.showwarning(
                            "Saved with warnings",
                            "Saved rebuilt RSB, but there were warnings:\n\n" + "\n".join(warnings),
                            parent=self,
                        )
                    return

                details = error_message or output or "unknown writer error"
                self._set_status(f"Save failed: {details}", error=True)
                messagebox.showerror(
                    "Save failed",
                    "PNG->RSB writer failed.\n\n"
                    f"Command:\n{shlex.join(command)}\n\n"
                    f"Output:\n{details}",
                    parent=self,
                )

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------- preview helpers

    def _set_preview_status(self, msg: str) -> None:
        if hasattr(self, "_preview_status_var"):
            self._preview_status_var.set(msg)

    def _clear_preview(self, msg: str = "No preview loaded.") -> None:
        self._preview_generation += 1
        self._preview_original_image = None
        self._preview_photo = None
        self._preview_path = None
        if hasattr(self, "_preview_canvas"):
            self._preview_canvas.itemconfigure(self._preview_image_item, image="")
            self._preview_canvas.configure(scrollregion=(0, 0, 0, 0))
        self._set_preview_status(msg)

    def _preview_commands(self, script: Path, rsb_path: Path, outdir: Path) -> list[list[str]]:
        """Build tolerant preview command attempts for common converter CLIs."""
        base = [sys.executable, str(script), str(rsb_path)]
        commands: list[list[str]] = []

        if script == CONVERTER_SCRIPT or script.name == CONVERTER_SCRIPT.name:
            commands.append(base + [
                "--argb8888-order", "argb",
                "--payload-shift", "0",
                "--group-by-format",
                "--group-output-dir", str(outdir),
                "--keep-going",
            ])
        else:
            commands.extend([
                base + ["--output-dir", str(outdir)],
                base + ["--outdir", str(outdir)],
                base + [str(outdir)],
            ])
            if CONVERTER_SCRIPT.exists():
                commands.append([
                    sys.executable, str(CONVERTER_SCRIPT), str(rsb_path),
                    "--argb8888-order", "argb",
                    "--payload-shift", "0",
                    "--group-by-format",
                    "--group-output-dir", str(outdir),
                    "--keep-going",
                ])

        # Preserve order, but remove duplicates.
        seen: set[tuple[str, ...]] = set()
        unique: list[list[str]] = []
        for cmd in commands:
            key = tuple(cmd)
            if key not in seen:
                seen.add(key)
                unique.append(cmd)
        return unique

    def _start_preview_render(self, path: Path) -> None:
        script = find_preview_converter()
        if script is None:
            self._clear_preview("Preview unavailable: no rsb2png.py or grouped converter found beside the viewer.")
            return

        self._preview_generation += 1
        generation = self._preview_generation
        outdir = self._preview_tempdir / f"preview_{generation}_{path.stem}"
        outdir.mkdir(parents=True, exist_ok=True)
        self._preview_original_image = None
        self._preview_photo = None
        if hasattr(self, "_preview_canvas"):
            self._preview_canvas.itemconfigure(self._preview_image_item, image="")
        self._set_preview_status(f"Rendering preview via {script.name}...")

        def worker() -> None:
            last_error = ""
            preview: Path | None = None
            used_cmd: list[str] | None = None
            for cmd in self._preview_commands(script, path, outdir):
                try:
                    completed = subprocess.run(
                        cmd,
                        cwd=str(SCRIPT_DIR),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=60,
                    )
                    output = completed.stdout.strip()
                    last_error = output[-600:] if output else f"exit {completed.returncode}"
                    candidate = choose_preview_png(outdir, path)
                    if candidate is not None:
                        preview = candidate
                        used_cmd = cmd
                        break
                except Exception as exc:
                    last_error = str(exc)

            def done() -> None:
                if generation != self._preview_generation:
                    return
                if preview is None:
                    self._clear_preview(f"Preview render failed: {last_error or 'no PNG produced'}")
                    return
                self._load_preview_image(preview)
                cmd_name = Path(used_cmd[1]).name if used_cmd and len(used_cmd) > 1 else script.name
                self._set_preview_status(f"Preview: {preview.name}  ({cmd_name})")

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _load_preview_image(self, png_path: Path) -> None:
        self._preview_path = png_path
        try:
            if Image is not None and ImageTk is not None:
                with Image.open(png_path) as im:  # type: ignore[union-attr]
                    self._preview_original_image = im.convert("RGBA")
                self._render_preview_image()
                return

            self._preview_photo = tk.PhotoImage(file=str(png_path))
            self._preview_canvas.itemconfigure(self._preview_image_item, image=self._preview_photo)
            self._preview_canvas.coords(self._preview_image_item, 12, 12)
            width = int(self._preview_photo.width()) + 24
            height = int(self._preview_photo.height()) + 24
            self._preview_canvas.configure(scrollregion=(0, 0, width, height))
        except Exception as exc:
            self._clear_preview(f"Preview PNG could not be displayed: {exc}")

    def _render_preview_image(self) -> None:
        if Image is None or ImageTk is None:
            return
        if self._preview_original_image is None or not hasattr(self, "_preview_canvas"):
            return

        img = self._preview_original_image
        width, height = img.size
        if width <= 0 or height <= 0:
            return

        canvas_w = max(1, self._preview_canvas.winfo_width() - 24)
        canvas_h = max(1, self._preview_canvas.winfo_height() - 24)
        scale = min(canvas_w / width, canvas_h / height)
        if scale >= 1:
            # Small game textures are easier to inspect with integer scaling.
            scale = float(max(1, min(16, int(scale))))
        else:
            scale = max(0.05, scale)

        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        resample = Image.Resampling.NEAREST if hasattr(Image, "Resampling") else Image.NEAREST  # type: ignore[attr-defined]
        display_img = img.resize(new_size, resample)
        self._preview_photo = ImageTk.PhotoImage(display_img)  # type: ignore[union-attr]
        self._preview_canvas.itemconfigure(self._preview_image_item, image=self._preview_photo)
        self._preview_canvas.coords(self._preview_image_item, 12, 12)
        self._preview_canvas.configure(scrollregion=(0, 0, new_size[0] + 24, new_size[1] + 24))

    def _on_app_close(self) -> None:
        try:
            shutil.rmtree(self._preview_tempdir, ignore_errors=True)
        finally:
            self.destroy()

    def _set_status(self, msg: str, error: bool = False) -> None:
        self._status_var.set(msg)
        self._status_lbl.configure(fg=WARNING_FG if error else TEXT_DIM)


# ---------------------------------------------------------------------------

def main() -> None:
    app = RSBViewer()
    app.mainloop()


if __name__ == "__main__":
    main()
