"""A friendly notification bar with action buttons (no pop-up dialogs)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

COLOURS = {"info": "#e7f3ff", "ok": "#e6f7ea", "warn": "#fff4d6"}


class Banner(tk.Frame):
    def __init__(self, master) -> None:
        super().__init__(master, background=COLOURS["info"], padx=8, pady=6,
                         highlightthickness=1, highlightbackground="#b8c7d9")
        self.text = tk.Label(self, background=COLOURS["info"], justify="left",
                             anchor="w", wraplength=700)
        self.text.pack(side="left", fill="x", expand=True)
        self.buttons = tk.Frame(self, background=COLOURS["info"])
        self.buttons.pack(side="right")
        self.visible = False

    def show(self, text: str, actions=(), kind: str = "info") -> None:
        colour = COLOURS.get(kind, COLOURS["info"])
        for w in (self, self.text, self.buttons):
            w.configure(background=colour)
        self.text.configure(text=text)
        for child in self.buttons.winfo_children():
            child.destroy()
        for label, fn in actions:
            ttk.Button(self.buttons, text=label, command=fn).pack(side="left", padx=2)
        ttk.Button(self.buttons, text="Dismiss", command=self.hide).pack(side="left", padx=2)
        if not self.visible:
            self.grid()
            self.visible = True

    def hide(self) -> None:
        if self.visible:
            self.grid_remove()
            self.visible = False
