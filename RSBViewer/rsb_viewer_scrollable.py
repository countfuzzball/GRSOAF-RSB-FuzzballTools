from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk


class ScrollableFrame(tk.Frame):
    """
    A reusable vertical scroll container for normal Tk widgets.

    Use `scrollable.inner` as the parent for labels, entries, checkbuttons,
    comboboxes, etc. The outer ScrollableFrame handles the canvas, scrollbar,
    scrollregion updates, and mouse-wheel bindings.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        bg: str,
        canvas_bg: str | None = None,
        scrollbar_style: str | None = None,
    ) -> None:
        super().__init__(parent, bg=bg)

        self.canvas = tk.Canvas(
            self,
            bg=canvas_bg if canvas_bg is not None else bg,
            highlightthickness=0,
            borderwidth=0,
        )
        self.vscrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            style=scrollbar_style,
        )
        self.canvas.configure(yscrollcommand=self.vscrollbar.set)

        self.vscrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Bind the base widgets immediately. Child widgets added later can be
        # covered by calling bind_mousewheel_to_children() after populating them.
        self._bind_mousewheel(self)
        self._bind_mousewheel(self.canvas)
        self._bind_mousewheel(self.inner)

    def _on_inner_configure(self, _event: tk.Event) -> None:  # type: ignore[type-arg]
        self.refresh()

    def _on_canvas_configure(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        # Make the embedded frame track the canvas width, so grid rows stretch
        # horizontally instead of creating an awkward narrow island.
        self.canvas.itemconfigure(self._window_id, width=event.width)
        self.refresh()

    def refresh(self) -> None:
        """Recalculate the scrollable region."""
        self.update_idletasks()
        bbox = self.canvas.bbox("all")
        self.canvas.configure(scrollregion=bbox if bbox is not None else (0, 0, 0, 0))

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0.0)

    def bind_mousewheel_to_children(self) -> None:
        """
        Route mouse-wheel events from all current child widgets to this scroll
        container. Call this after dynamically rebuilding the inner frame.
        """
        self._bind_mousewheel_recursive(self.inner)

    def _bind_mousewheel_recursive(self, widget: tk.Misc) -> None:
        self._bind_mousewheel(widget)
        try:
            children = widget.winfo_children()
        except Exception:
            return
        for child in children:
            self._bind_mousewheel_recursive(child)

    def _bind_mousewheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_linux_scroll_up, add="+")
        widget.bind("<Button-5>", self._on_linux_scroll_down, add="+")

    def _on_mousewheel(self, event: tk.Event) -> str:  # type: ignore[type-arg]
        delta = int(getattr(event, "delta", 0))
        if delta == 0:
            return "break"

        if sys.platform == "darwin":
            # macOS deltas are usually small and not multiples of 120.
            units = -1 if delta > 0 else 1
        else:
            units = int(-delta / 120)
            if units == 0:
                units = -1 if delta > 0 else 1

        self.canvas.yview_scroll(units, "units")
        return "break"

    def _on_linux_scroll_up(self, _event: tk.Event) -> str:  # type: ignore[type-arg]
        self.canvas.yview_scroll(-3, "units")
        return "break"

    def _on_linux_scroll_down(self, _event: tk.Event) -> str:  # type: ignore[type-arg]
        self.canvas.yview_scroll(3, "units")
        return "break"
