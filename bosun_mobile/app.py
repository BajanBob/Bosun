"""Bosun Mobile: phone front end for Bosun radio control over the network."""

from __future__ import annotations

import asyncio
import functools

import toga
from toga.style.pack import COLUMN, ROW, Pack

from bosun.version import __version__

from .controller import Controller, describe_catalogue, format_status, models, modes_for

GAP = 6


def row(*children) -> toga.Box:
    return toga.Box(children=list(children), style=Pack(direction=ROW, margin_bottom=GAP))


def label(text: str) -> toga.Label:
    return toga.Label(text, style=Pack(width=110, margin_right=GAP))


class BosunMobile(toga.App):
    def startup(self) -> None:
        self.ctl = Controller()
        self.main_window = toga.MainWindow(title=f"Bosun {__version__}")
        self.main_window.content = toga.OptionContainer(content=[
            ("Radio", toga.ScrollContainer(content=self._radio_tab(), horizontal=False)),
            ("Scan", toga.ScrollContainer(content=self._scan_tab(), horizontal=False)),
            ("Radios", self._catalogue_tab()),
        ])
        self.main_window.show()

    # ---------- layout ----------
    def _radio_tab(self) -> toga.Box:
        first = models()[0]
        self.model = toga.Selection(items=models(), on_change=self._model_changed,
                                    style=Pack(flex=1))
        self.host = toga.TextInput(placeholder="e.g. 192.168.1.50", style=Pack(flex=1))
        self.port = toga.TextInput(placeholder="e.g. 4000", style=Pack(flex=1))
        self.connect_btn = toga.Button("Connect", on_press=self._toggle_connect,
                                       style=Pack(flex=1))
        self.freq = toga.TextInput(placeholder="MHz, e.g. 145.500", style=Pack(flex=1))
        self.mode = toga.Selection(items=modes_for(first), style=Pack(flex=1))
        self.status = toga.MultilineTextInput(readonly=True, value="Not connected.",
                                              style=Pack(height=130))
        self.message = toga.Label("", style=Pack(margin_top=GAP))
        return toga.Box(style=Pack(direction=COLUMN, margin=10), children=[
            toga.Label("Connect to your radio through a serial-to-network adapter "
                       "(ser2net, LAN-to-serial or Wi-Fi bridge).",
                       style=Pack(margin_bottom=10)),
            row(label("Radio"), self.model),
            row(label("Host / IP"), self.host),
            row(label("TCP port"), self.port),
            row(self.connect_btn),
            toga.Divider(style=Pack(margin_top=GAP, margin_bottom=GAP)),
            row(label("Frequency"), self.freq),
            row(label("Mode"), self.mode),
            row(toga.Button("Tune", on_press=self._tune, style=Pack(flex=1, margin_right=GAP)),
                toga.Button("Read status", on_press=self._refresh, style=Pack(flex=1))),
            self.status,
            self.message,
        ])

    def _scan_tab(self) -> toga.Box:
        self.scan_start = toga.TextInput(placeholder="MHz", style=Pack(flex=1))
        self.scan_stop = toga.TextInput(placeholder="MHz", style=Pack(flex=1))
        self.scan_step = toga.TextInput(value="25", style=Pack(flex=1))
        self.scan_dwell = toga.TextInput(value="0.6", style=Pack(flex=1))
        self.scan_btn = toga.Button("Start scan", on_press=self._toggle_scan,
                                    style=Pack(flex=1))
        self.scan_now = toga.Label("Idle")
        self.scan_log = toga.MultilineTextInput(readonly=True, style=Pack(height=220))
        return toga.Box(style=Pack(direction=COLUMN, margin=10), children=[
            toga.Label("Range scan on the connected radio. Hits are logged when the "
                       "radio reports open squelch.", style=Pack(margin_bottom=10)),
            row(label("Start (MHz)"), self.scan_start),
            row(label("Stop (MHz)"), self.scan_stop),
            row(label("Step (kHz)"), self.scan_step),
            row(label("Dwell (s)"), self.scan_dwell),
            row(self.scan_btn),
            self.scan_now,
            self.scan_log,
        ])

    def _catalogue_tab(self) -> toga.Box:
        return toga.Box(style=Pack(direction=COLUMN, margin=10), children=[
            toga.MultilineTextInput(readonly=True, value=describe_catalogue(),
                                    style=Pack(flex=1)),
        ])

    # ---------- helpers ----------
    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))

    def _say(self, text: str) -> None:
        self.message.text = text

    def _from_thread(self, fn, *args) -> None:
        self.loop.call_soon_threadsafe(fn, *args)

    # ---------- handlers ----------
    def _model_changed(self, widget) -> None:
        if widget.value:
            self.mode.items = modes_for(widget.value)

    async def _toggle_connect(self, widget) -> None:
        widget.enabled = False
        try:
            if self.ctl.connected:
                await self._run(self.ctl.disconnect)
                self.status.value = "Not connected."
                widget.text = "Connect"
                self._say("Disconnected.")
            else:
                self._say("Connecting...")
                st = await self._run(self.ctl.connect, self.model.value,
                                     self.host.value, self.port.value)
                self.status.value = format_status(st)
                widget.text = "Disconnect"
                self._say("Connected.")
        except Exception as exc:
            self._say(f"Error: {exc}")
        finally:
            widget.enabled = True

    async def _tune(self, widget) -> None:
        try:
            st = await self._run(self.ctl.tune, self.freq.value, self.mode.value)
            self.status.value = format_status(st)
            self._say("Tuned.")
        except Exception as exc:
            self._say(f"Error: {exc}")

    async def _refresh(self, widget) -> None:
        try:
            self.status.value = format_status(await self._run(self.ctl.status))
            self._say("")
        except Exception as exc:
            self._say(f"Error: {exc}")

    def _show_step(self, hz: float) -> None:
        self.scan_now.text = f"Scanning {hz / 1e6:.6f} MHz"

    def _show_hit(self, hz: float) -> None:
        self.scan_log.value = f"HIT {hz / 1e6:.6f} MHz\n" + self.scan_log.value

    async def _toggle_scan(self, widget) -> None:
        try:
            if self.ctl.scan is not None:
                await self._run(self.ctl.stop_scan)
                widget.text = "Start scan"
                self.scan_now.text = "Stopped"
                return
            self.ctl.start_scan(
                self.scan_start.value, self.scan_stop.value,
                self.scan_step.value, self.scan_dwell.value,
                on_step=lambda hz: self._from_thread(self._show_step, hz),
                on_hit=lambda hz: self._from_thread(self._show_hit, hz),
            )
            widget.text = "Stop scan"
            if not self.ctl.supports_squelch():
                self.scan_log.value = ("This radio cannot report squelch, so hits "
                                       "will not be logged.\n") + self.scan_log.value
        except Exception as exc:
            self.scan_now.text = f"Error: {exc}"


def main() -> BosunMobile:
    return BosunMobile("Bosun Mobile", "io.github.bajanbob.bosun_mobile")
