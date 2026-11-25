"""Cognitive touch-screen faceplate: a radio-style front panel for touch screens.

Big ON button, large frequency display (swipe to tune), live spectrum strip
(tap to tune), cognitive signal tiles (tap to tune, AUTO follows the busiest
signal), mode and step keys. Green-and-gold day theme; red night-vision theme.
"""

from __future__ import annotations

import time
import tkinter as tk

import numpy as np

from .. import chirp
from ..raster import Waterfall, make_palette, png_bytes

THEMES = {
    "day": {
        "bg": "#0a3326", "panel": "#0f4a37", "panel2": "#135c44", "edge": "#c9a227",
        "gold": "#d4af37", "gold2": "#f2d675", "text": "#f5ecd0", "dim": "#9fbfae",
        "on": "#2ecc71", "on_glow": "#7dffb0", "off": "#123d2f", "warn": "#ffb347",
        "new": "#ff7aa8",
        "spec": {"bg": (8, 38, 28), "grid": (24, 74, 56), "trace": (242, 214, 117),
                 "fill": (30, 92, 62), "mark": (212, 175, 55), "select": (125, 255, 176),
                 "palette": make_palette([(0, (6, 30, 22)), (0.35, (20, 100, 60)),
                                          (0.65, (190, 160, 40)), (1, (255, 245, 200))])},
    },
    "night": {
        "bg": "#000000", "panel": "#120000", "panel2": "#1c0303", "edge": "#5a0f0f",
        "gold": "#b32020", "gold2": "#d23a3a", "text": "#c22a2a", "dim": "#6e1818",
        "on": "#9a1515", "on_glow": "#e04040", "off": "#140202", "warn": "#c22a2a",
        "new": "#ff4040",
        "spec": {"bg": (0, 0, 0), "grid": (40, 6, 6), "trace": (210, 40, 40),
                 "fill": (60, 8, 8), "mark": (200, 40, 40), "select": (255, 70, 70),
                 "palette": make_palette([(0, (0, 0, 0)), (0.5, (90, 10, 10)),
                                          (1, (255, 60, 60))])},
    },
}
STEPS = [(100, "100 Hz"), (1_000, "1k"), (5_000, "5k"), (12_500, "12.5k"),
         (25_000, "25k"), (100_000, "100k")]
MODES = ["FM", "AM", "USB", "LSB", "CW"]
TIPS = {
    "power": "ON: connects your saved radio and starts the live spectrum with the "
             "cognitive receiver. Press again to switch everything off.",
    "night": "Night mode: dim red on black so your eyes stay adapted to the dark.",
    "full": "Full screen for a dedicated touch display. Esc leaves full screen.",
    "close": "Close the faceplate and return to the normal window.",
    "rec": "Record the faceplate as a video (saved in 'Bosun Recordings').",
    "listen": "LISTEN: hear the tuned signal through the speakers (from the SDR).",
    "freq": "Swipe left or right on the frequency to tune. Tap a digit side to step.",
    "down": "Tune down by the selected step.", "up": "Tune up by the selected step.",
    "spec": "Live spectrum and waterfall. Tap a signal to tune to it.",
    "auto": "AUTO: the cognitive receiver follows the busiest active signal for you.",
    "scan": "SCAN: hop through the signals the cognitive receiver has found.",
    "tile": "A signal the cognitive receiver found. Tap to tune to it.",
    "mode": "Demodulation mode sent to the radio.",
    "step": "How far each tuning step or swipe moves.",
}


class Faceplate(tk.Toplevel):
    def __init__(self, app) -> None:
        super().__init__(app.root)
        self.app = app
        self.title("Bosun faceplate")
        self.geometry("1024x600")
        self.minsize(800, 480)
        self.theme_name = "night" if app.settings.get("faceplate_night") else "day"
        self.t = THEMES[self.theme_name]
        self.canvas = tk.Canvas(self, highlightthickness=0, background=self.t["bg"])
        self.canvas.pack(fill="both", expand=True)
        self.hits: list[tuple[tuple[float, float, float, float], str, object]] = []
        self.freq_hz = self._initial_freq()
        self.step = int(app.settings.get("faceplate_step", 12_500))
        self.mode = app.mode.get() or "FM"
        self.auto = False
        self.scan = False
        self._scan_i = 0
        self._last_auto = 0.0
        self._drag: tuple[int, float] | None = None
        self._photo = None
        self.tip = ""
        self.recorder = None
        self.fall = Waterfall(600, 90, 110, self.t["spec"])
        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Motion>", self._hover)
        self.bind("<Escape>", lambda _e: self.attributes("-fullscreen", False))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(50, self.redraw)
        self.after(120, self._tick)

    # ------------------------------------------------------------------ state
    def _initial_freq(self) -> float:
        try:
            return float(self.app.freq.get()) * 1e6
        except ValueError:
            pass
        sp = self.app.spectrum
        if sp is not None:
            try:
                return sp._center_hz()
            except Exception:
                pass
        return 145.5e6

    @property
    def powered(self) -> bool:
        sp = self.app.spectrum
        return bool(self.app.ctl.connected or (sp is not None and sp._worker is not None))

    def _cog(self):
        sp = self.app.spectrum
        return sp.cog if sp is not None else None

    # ------------------------------------------------------------------ actions
    def power(self) -> None:
        app, sp = self.app, self.app.spectrum
        if self.powered:
            if sp is not None and sp._worker is not None:
                sp.stop()
            if app.ctl.connected:
                app._toggle_connect()
            self.auto = self.scan = False
            app.say("Faceplate: off.")
        else:
            s = app.settings
            if s.get("model") and (s.get("port") or s.get("tcp")) and not app.ctl.connected:
                app._toggle_connect()
            if sp is not None and sp._worker is None:
                sp.center.set(f"{self.freq_hz / 1e6:.4f}")
                sp.auto.set(True)
                sp.cognitive.set(True)
                sp.toggle()
            app.say("Faceplate: on.")
        self.redraw()

    def tune(self, hz: float, mode: str | None = None) -> None:
        self.freq_hz = max(10_000.0, round(hz / 10) * 10)
        if mode:
            self.mode = mode
        app, sp = self.app, self.app.spectrum
        app.freq.set(f"{self.freq_hz / 1e6:.6f}")
        if mode:
            app.mode.set(mode)
        if app.ctl.connected and not app.ctl.audio_only:
            app._bg(app.ctl.tune, app.freq.get(), mode, done=app._show_status)
        if sp is not None:
            sp.selected_hz = self.freq_hz
            if mode:
                sp.rec_mode.set({"NFM": "FM"}.get(mode, mode))
            sp._listen_retarget()
            src = sp.source
            if src is not None and abs(self.freq_hz - src.center_hz) > src.rate * 0.4:
                sp.retune(self.freq_hz)
        self.redraw()

    def toggle_night(self) -> None:
        self.theme_name = "day" if self.theme_name == "night" else "night"
        self.t = THEMES[self.theme_name]
        self.fall.set_theme(self.t["spec"])
        try:
            from .. import config
            config.save_settings({"faceplate_night": self.theme_name == "night"})
        except Exception:
            pass
        self.redraw()

    def toggle_full(self) -> None:
        self.attributes("-fullscreen", not bool(self.attributes("-fullscreen")))

    def toggle_listen(self) -> None:
        sp = self.app.spectrum
        if sp is None:
            return
        if sp.listener is None:
            if not self.powered:
                self.power()
            sp.selected_hz = self.freq_hz
            sp.rec_mode.set({"NFM": "FM"}.get(self.mode, self.mode))
            self.after(400, lambda: (sp.toggle_listen(), self.redraw()))
        else:
            sp.toggle_listen()
        self.redraw()

    def toggle_rec(self) -> None:
        from ..recorder import recordings_dir, stamp
        from ..videorec import WindowRecorder

        if self.recorder is not None:
            rec, self.recorder = self.recorder, None
            path = rec.stop()
            msg = (f"Faceplate video saved ({rec.rec.kind}): {path}" if path else
                   f"Could not record the screen: {rec.error}")
            self.app.say(msg)
        else:
            self.recorder = WindowRecorder(self.canvas, recordings_dir() /
                                           stamp("faceplate_video"))
            self.recorder.start()
            self.app.say("Recording the faceplate...")
        self.redraw()

    def close(self) -> None:
        if self.recorder is not None:
            self.toggle_rec()
        try:
            from .. import config
            config.save_settings({"faceplate_step": self.step})
        except Exception:
            pass
        self.app.faceplate = None
        self.destroy()

    # ------------------------------------------------------------------ input
    def _hit(self, x, y):
        for (x0, y0, x1, y1), key, fn in reversed(self.hits):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return key, fn
        return None, None

    def _press(self, e) -> None:
        key, fn = self._hit(e.x, e.y)
        if key == "freq":
            self._drag = (e.x, self.freq_hz)
        elif key == "spec":
            self._tap_spectrum(e.x)
        elif fn is not None:
            fn()

    def _motion(self, e) -> None:
        if self._drag is not None:
            x0, f0 = self._drag
            steps = int((e.x - x0) / 18)
            new = f0 + steps * self.step
            if new != self.freq_hz:
                self.freq_hz = max(10_000.0, new)
                self.redraw()

    def _release(self, _e) -> None:
        if self._drag is not None:
            moved = self.freq_hz != self._drag[1]
            self._drag = None
            if moved:
                self.tune(self.freq_hz)

    def _hover(self, e) -> None:
        key, _ = self._hit(e.x, e.y)
        key = (key or "").split(":")[0]
        tip = TIPS.get(key, "")
        if tip != self.tip:
            self.tip = tip
            self.canvas.itemconfigure("tipline", text=tip)

    def _tap_spectrum(self, x) -> None:
        sp = self.app.spectrum
        if sp is None or self.fall.freqs is None:
            return
        x0 = self._spec_box[0]
        f = self.fall.freqs
        hz = float(f[0] + (x - x0) / self.fall.w * (f[-1] - f[0]))
        for d in sp.detections:
            if abs(d.center_hz - hz) <= max(d.bandwidth_hz / 2, 3000):
                self.tune(d.center_hz, chirp.record_mode_for(d.kind))
                return
        self.tune(hz)

    # ------------------------------------------------------------------ drawing
    def _rrect(self, x0, y0, x1, y1, r, **kw):
        r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def _button(self, box, text, key, fn, *, active=False, size=None, colour=None):
        t = self.t
        x0, y0, x1, y1 = box
        fill = (colour or t["gold"]) if active else t["panel2"]
        self._rrect(x0, y0, x1, y1, 12, fill=fill, outline=t["edge"], width=2)
        fs = size or max(10, int((y1 - y0) * 0.32))
        self.canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text,
                                fill=t["bg"] if active else t["gold2"],
                                font=("Helvetica", fs, "bold"))
        self.hits.append((box, key, fn))

    def redraw(self) -> None:
        c, t = self.canvas, self.t
        W, H = max(c.winfo_width(), 800), max(c.winfo_height(), 480)
        c.delete("all")
        c.configure(background=t["bg"])
        self.hits = []
        pad = W * 0.012
        top_h = H * 0.09
        # ---- top bar
        self._rrect(pad, pad, W - pad, pad + top_h, 14, fill=t["panel"], outline=t["edge"],
                    width=2)
        c.create_text(pad * 3, pad + top_h / 2, anchor="w", text="BOSUN",
                      fill=t["gold"], font=("Helvetica", int(top_h * 0.45), "bold"))
        cog = self._cog()
        active = [s for s in (cog.ranked() if cog else []) if s.active]
        status = ("COGNITIVE RECEIVER · OFF" if not self.powered else
                  f"COGNITIVE · LEARNING · {len(active)} ACTIVE · "
                  f"{len(cog.signals) if cog else 0} LOGGED")
        bw = top_h * 1.5
        buttons_x0 = W - pad * 2 - 5 * bw - 4 * pad
        utc = time.strftime("%H:%M UTC", time.gmtime())
        c.create_text(buttons_x0 - pad * 2, pad + top_h / 2, anchor="e", text=utc,
                      fill=t["dim"], font=("Helvetica", int(top_h * 0.25)), tags="clock")
        c.create_text(pad * 3 + top_h * 3.0, pad + top_h / 2, anchor="w", text=status,
                      fill=t["gold2"], font=("Helvetica", int(min(top_h * 0.24, W * 0.016)),
                                             "bold"), tags="status")
        bx = W - pad * 2
        for label, key, fn in (("✕", "close", self.close), ("⛶", "full", self.toggle_full),
                               ("☾" if self.theme_name == "day" else "☀", "night",
                                self.toggle_night),
                               ("● REC", "rec", self.toggle_rec),
                               ("♪ LISTEN", "listen", self.toggle_listen)):
            sp = self.app.spectrum
            active = (key == "night" and self.theme_name == "night") or \
                (key == "rec" and self.recorder is not None) or \
                (key == "listen" and sp is not None and sp.listener is not None)
            self._button((bx - bw, pad * 1.8, bx, pad + top_h - pad * 0.8), label, key, fn,
                         size=int(top_h * 0.3), active=active,
                         colour=t["warn"] if key == "rec" else None)
            bx -= bw + pad

        body_y = pad * 2 + top_h
        bottom_h = H * 0.15
        tipline_h = H * 0.04
        body_h = H - body_y - bottom_h - tipline_h - pad * 2
        left_w, right_w = W * 0.20, W * 0.27
        mid_x0, mid_x1 = pad + left_w + pad, W - pad - right_w - pad

        # ---- ON button
        cx, cy = pad + left_w / 2, body_y + body_h * 0.42
        r = min(left_w, body_h) * 0.36
        on = self.powered
        if on:
            for k in range(4, 0, -1):
                c.create_oval(cx - r - k * 4, cy - r - k * 4, cx + r + k * 4, cy + r + k * 4,
                              outline=t["on_glow"], width=1)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=t["on"] if on else t["off"],
                      outline=t["gold"], width=max(3, int(r * 0.08)))
        c.create_arc(cx - r * 0.45, cy - r * 0.45, cx + r * 0.45, cy + r * 0.45, start=120,
                     extent=300, style="arc", outline=t["text"] if on else t["gold"],
                     width=max(3, int(r * 0.09)))
        c.create_line(cx, cy - r * 0.55, cx, cy - r * 0.05, fill=t["text"] if on else t["gold"],
                      width=max(3, int(r * 0.09)), capstyle="round")
        c.create_text(cx, cy + r * 0.62, text="ON" if on else "OFF", fill=t["text"],
                      font=("Helvetica", int(r * 0.22), "bold"))
        self.hits.append(((cx - r, cy - r, cx + r, cy + r), "power", self.power))
        # AUTO / SCAN under the button
        by = body_y + body_h * 0.80
        bh = body_h * 0.16
        half = left_w / 2 - pad / 2
        self._button((pad, by, pad + half, by + bh), "AUTO", "auto", self._toggle_auto,
                     active=self.auto, colour=t["on"])
        self._button((pad + half + pad, by, pad + left_w, by + bh), "SCAN", "scan",
                      self._toggle_scan, active=self.scan, colour=t["on"])

        # ---- frequency display
        fh = body_h * 0.34
        fbox = (mid_x0, body_y, mid_x1, body_y + fh)
        self._rrect(*fbox, 16, fill=t["panel"], outline=t["edge"], width=2)
        mhz = self.freq_hz / 1e6
        text = f"{mhz:,.5f}".replace(",", " ")
        box_w = fbox[2] - fbox[0]
        unit_w = box_w * 0.12
        # Courier glyphs are ~0.6 em wide: fit the digits beside the MHz label.
        size = int(min(fh * 0.40, (box_w - unit_w - pad * 4) / (len(text) * 0.62)))
        digits_y = fbox[1] + fh * 0.52
        c.create_text(fbox[0] + pad * 2 + (box_w - unit_w - pad * 2) / 2, digits_y,
                      text=text, fill=t["gold2"], font=("Courier", size, "bold"))
        c.create_text(fbox[2] - pad * 2, digits_y + size * 0.25, anchor="e", text="MHz",
                      fill=t["dim"], font=("Helvetica", int(fh * 0.12), "bold"))
        c.create_text(fbox[0] + pad * 2, fbox[1] + fh * 0.12, anchor="w", text=self.mode,
                      fill=t["gold"], font=("Helvetica", int(fh * 0.12), "bold"))
        c.create_text(fbox[0] + pad * 2, fbox[3] - fh * 0.12, anchor="w",
                      text=f"step {self._step_label()}   ◀ swipe ▶", fill=t["dim"],
                      font=("Helvetica", int(fh * 0.10)))
        self.hits.append((fbox, "freq", None))
        # signal meter
        level = self._level()
        mx0, mx1 = fbox[0] + (fbox[2] - fbox[0]) * 0.45, fbox[2] - pad * 2
        my = fbox[3] - fh * 0.12
        segs = 20
        for i in range(segs):
            sx0 = mx0 + (mx1 - mx0) * i / segs
            lit = level is not None and i < level / 60 * segs
            colour = (t["gold"] if i < segs * 0.6 else t["warn"]) if lit else t["panel2"]
            c.create_rectangle(sx0, my - fh * 0.05, sx0 + (mx1 - mx0) / segs - 2,
                               my + fh * 0.05, fill=colour, outline="")
        # ---- spectrum strip
        sy0 = body_y + fh + pad
        sy1 = body_y + body_h
        tb = (sy1 - sy0) * 0.22
        self._button((mid_x0, sy0, mid_x0 + tb * 1.6, sy0 + tb), "◀", "down",
                     lambda: self.tune(self.freq_hz - self.step))
        self._button((mid_x1 - tb * 1.6, sy0, mid_x1, sy0 + tb), "▶", "up",
                     lambda: self.tune(self.freq_hz + self.step))
        sx = mid_x0 + tb * 1.6 + pad
        sw = (mid_x1 - tb * 1.6 - pad) - sx
        for i, (hz, label) in enumerate(STEPS):
            w = sw / len(STEPS)
            fs = max(8, int(min(tb * 0.30, (w - 6) / (len(label) * 0.62))))
            self._button((sx + i * w + 2, sy0, sx + (i + 1) * w - 2, sy0 + tb), label,
                         f"step:{hz}", lambda hz=hz: self._set_step(hz),
                         active=(hz == self.step), size=fs)
        self._spec_box = (int(mid_x0), int(sy0 + tb + pad), int(mid_x1), int(sy1))
        x0, y0, x1, y1 = self._spec_box
        self._rrect(x0 - 2, y0 - 2, x1 + 2, y1 + 2, 8, fill=t["panel"], outline=t["edge"],
                    width=2)
        self.fall.resize(x1 - x0, int((y1 - y0) * 0.45), int((y1 - y0) * 0.55))
        c.create_image(x0, y0, anchor="nw", tags="spec")
        self.hits.append((self._spec_box, "spec", None))
        self._draw_spectrum()

        # ---- cognitive tiles
        rx0, rx1 = W - pad - right_w, W - pad
        self._rrect(rx0, body_y, rx1, body_y + body_h, 14, fill=t["panel"], outline=t["edge"],
                    width=2)
        c.create_text(rx0 + pad * 1.5, body_y + pad * 1.6, anchor="w", text="SIGNALS",
                      fill=t["gold"], font=("Helvetica", int(H * 0.025), "bold"))
        new_ids = {id(s) for s in (cog.new_signals() if cog else [])}
        tiles = (cog.ranked() if cog else [])[:6]
        th = (body_h - pad * 4) / 6.4
        for i, sig in enumerate(tiles):
            ty = body_y + pad * 3.2 + i * th
            box = (rx0 + pad, ty, rx1 - pad, ty + th - pad * 0.6)
            sel = abs(sig.center_hz - self.freq_hz) < max(sig.bandwidth_hz / 2, 2000)
            self._rrect(*box, 10, fill=t["gold"] if sel else t["panel2"], outline=t["edge"])
            fg = t["bg"] if sel else t["text"]
            c.create_text(box[0] + pad, box[1] + th * 0.28, anchor="w",
                          text=f"{sig.center_hz / 1e6:.4f}", fill=fg,
                          font=("Courier", int(th * 0.30), "bold"))
            c.create_text(box[0] + pad, box[1] + th * 0.66, anchor="w",
                          text=f"{sig.kind}  {sig.activity:.0%}", fill=fg if sel else t["dim"],
                          font=("Helvetica", int(th * 0.18)))
            dot = t["on_glow"] if sig.active else t["edge"]
            c.create_oval(box[2] - pad * 2.2, box[1] + th * 0.2, box[2] - pad, box[1] + th * 0.2
                          + pad * 1.2, fill=dot, outline="")
            if id(sig) in new_ids:
                c.create_text(box[2] - pad * 3, box[1] + th * 0.66, anchor="e", text="NEW",
                              fill=t["new"], font=("Helvetica", int(th * 0.18), "bold"))
            self.hits.append((box, "tile", lambda s=sig: self.tune(
                s.center_hz, chirp.record_mode_for(s.kind))))
        if not tiles:
            c.create_text((rx0 + rx1) / 2, body_y + body_h / 2, width=right_w - pad * 4,
                          text=("Press ON. Signals the cognitive receiver finds appear here."
                                if not self.powered else "Listening..."),
                          fill=t["dim"], font=("Helvetica", int(H * 0.022)), justify="center")

        # ---- bottom: modes
        by0 = H - pad - tipline_h - bottom_h
        mw = (W - pad * 2) / len(MODES)
        for i, m in enumerate(MODES):
            self._button((pad + i * mw + 3, by0, pad + (i + 1) * mw - 3, by0 + bottom_h - pad),
                         m, "mode", lambda m=m: self.tune(self.freq_hz, m),
                         active=(m == self.mode))
        c.create_text(pad * 2, H - pad - tipline_h / 2, anchor="w", text=self.tip,
                      fill=t["dim"], font=("Helvetica", int(tipline_h * 0.45)), tags="tipline")

    def _step_label(self) -> str:
        return dict(STEPS).get(self.step, f"{self.step} Hz")

    def _set_step(self, hz: int) -> None:
        self.step = hz
        self.redraw()

    def _toggle_auto(self) -> None:
        self.auto = not self.auto
        if self.auto:
            self.scan = False
        self.redraw()

    def _toggle_scan(self) -> None:
        self.scan = not self.scan
        if self.scan:
            self.auto = False
        self.redraw()

    def _level(self) -> float | None:
        sp = self.app.spectrum
        if sp is None or sp.view.last is None or not self.powered:
            return None
        lv = sp.view.level_at(self.freq_hz)
        if lv is None:
            return None
        return max(0.0, lv - float(np.median(sp.view.last[1])))

    def _draw_spectrum(self) -> None:
        sp = self.app.spectrum
        if sp is None or sp.view.last is None or not self.powered:
            img = np.empty((self.fall.spec_h + self.fall.water_h, self.fall.w, 3), np.uint8)
            img[:] = self.fall.c["bg"]
        else:
            img = self.fall.render(sp.detections, self.freq_hz)
        self._photo = tk.PhotoImage(data=png_bytes(img))
        self.canvas.itemconfigure("spec", image=self._photo)

    # ------------------------------------------------------------------ loop
    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        sp = self.app.spectrum
        if sp is not None and sp.view.last is not None and self.powered:
            f, p = sp.view.last
            if self.fall.freqs is None or id(p) != getattr(self, "_last_p", None):
                self._last_p = id(p)
                self.fall.push(f, p)
            self._draw_spectrum()
            now = time.monotonic()
            cog = self._cog()
            if cog and now - self._last_auto > 2.0 and (self.auto or self.scan):
                self._last_auto = now
                active = [s for s in cog.ranked() if s.active]
                if active:
                    if self.auto:
                        target = active[0]
                    else:
                        self._scan_i = (self._scan_i + 1) % len(active)
                        target = active[self._scan_i]
                    if abs(target.center_hz - self.freq_hz) > 1000:
                        self.tune(target.center_hz, chirp.record_mode_for(target.kind))
            if now - getattr(self, "_last_full", 0.0) > 1.0:
                self._last_full = now
                self.redraw()
        self.after(150, self._tick)
