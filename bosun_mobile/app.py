"""Bosun Mobile: phone front end for Bosun radio control over the network."""

from __future__ import annotations

import asyncio
import functools

import toga
from toga.style.pack import COLUMN, ROW, Pack

from bosun.control import Controller, describe_catalogue, format_status, models, modes_for
from bosun.version import __version__

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
            ("SDR", toga.ScrollContainer(content=self._sdr_tab(), horizontal=False)),
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

    def _sdr_tab(self) -> toga.Box:
        from bosun.cognitive import CognitiveReceiver
        from bosun.raster import Waterfall

        self.sdr_source = None
        self.sdr_task = None
        self.sdr_selected = None
        self.cog = CognitiveReceiver(sensitivity=0.5)
        self.fall = Waterfall(480, 110, 170)
        self.sdr_kind = toga.Selection(items=[
            "RTL-SDR on this phone (USB OTG)", "rtl_tcp on the network", "Demo (simulated)"],
            style=Pack(flex=1))
        self.sdr_host = toga.TextInput(value="192.168.1.10:1234", style=Pack(flex=1))
        self.sdr_center = toga.TextInput(value="145.2", style=Pack(flex=1))
        self.sdr_rate = toga.Selection(items=["1.024 MHz", "2.048 MHz", "250 kHz"],
                                       style=Pack(flex=1))
        self.sdr_gain = toga.Slider(min=0, max=50, value=30, style=Pack(flex=1),
                                    on_release=self._sdr_gain)
        self.sdr_btn = toga.Button("Start", on_press=self._sdr_toggle, style=Pack(flex=1))
        self.sdr_view = toga.ImageView(style=Pack(height=280, margin_top=GAP))
        self.sdr_info = toga.Label("Plug the RTL-SDR in with a USB OTG adapter, then Start.")
        self.sdr_table = toga.Table(columns=["MHz", "Type", "SNR", "Busy"],
                                    on_select=self._sdr_pick, style=Pack(height=220))
        return toga.Box(style=Pack(direction=COLUMN, margin=10), children=[
            toga.Label("Live spectrum and automatic signal detection. On this phone the "
                       "free 'Rtl-sdr driver' app (Martin Marinov, F-Droid / Play) "
                       "handles the USB dongle.", style=Pack(margin_bottom=10)),
            row(label("Source"), self.sdr_kind),
            row(label("rtl_tcp host"), self.sdr_host),
            row(label("Centre MHz"), self.sdr_center),
            row(label("Span"), self.sdr_rate),
            row(label("Gain dB"), self.sdr_gain),
            row(self.sdr_btn,
                toga.Button("Retune", on_press=self._sdr_retune,
                            style=Pack(flex=1, margin_left=GAP))),
            self.sdr_view,
            self.sdr_info,
            toga.Label("Signals found (tap one to tune the connected radio):",
                       style=Pack(margin_top=GAP)),
            self.sdr_table,
        ])

    def _sdr_rate_hz(self) -> float:
        return {"1.024 MHz": 1.024e6, "2.048 MHz": 2.048e6,
                "250 kHz": 0.25e6}.get(str(self.sdr_rate.value), 1.024e6)

    async def _sdr_toggle(self, widget) -> None:
        if self.sdr_source is not None:
            await self._sdr_stop()
            return
        from bosun.control import parse_mhz
        from bosun.sources import DemoSource, RtlTcpSource, parse_rtl_tcp

        try:
            center = parse_mhz(self.sdr_center.value)
        except Exception as exc:
            self.sdr_info.text = f"Error: {exc}"
            return
        rate = self._sdr_rate_hz()
        kind = str(self.sdr_kind.value)
        widget.enabled = False
        try:
            if kind.startswith("Demo"):
                src = DemoSource(center, rate)
            elif kind.startswith("RTL-SDR on this phone"):
                src = await self._start_phone_dongle(center, rate)
                if src is None:
                    return
            else:
                host, port = parse_rtl_tcp(self.sdr_host.value)
                src = RtlTcpSource(host, port, center, rate, self.sdr_gain.value)
                self.sdr_info.text = f"Connecting to {host}:{port}..."
                await self._run(src.open)
        except Exception as exc:
            self.sdr_info.text = f"Error: {exc}"
            return
        finally:
            widget.enabled = True
        self.sdr_source = src
        self.cog.reset()
        widget.text = "Stop"
        self.sdr_info.text = f"Running: {src.name}"
        self.sdr_task = asyncio.ensure_future(self._sdr_loop())

    async def _start_phone_dongle(self, center: float, rate: float):
        from bosun.sources import RtlTcpSource

        from . import android_sdr

        if not android_sdr.on_android():
            self.sdr_info.text = ("This option is for Android. On a computer use the "
                                  "desktop app, or rtl_tcp on the network.")
            return None
        try:
            android_sdr.start_driver(self, int(rate))
        except Exception:
            self.sdr_info.text = ("The free 'Rtl-sdr driver' app is needed for USB "
                                  "dongles. Opening its store page...")
            android_sdr.open_driver_store_page(self)
            return None
        self.sdr_info.text = ("Waiting for the driver (allow USB access if Android "
                              "asks)...")
        last = None
        for _ in range(30):  # about 15 s for the permission prompt
            await asyncio.sleep(0.5)
            src = RtlTcpSource("127.0.0.1", android_sdr.PORT, center, rate,
                               self.sdr_gain.value, connect_timeout=1.0)
            try:
                await self._run(src.open)
                return src
            except Exception as exc:
                last = exc
        self.sdr_info.text = (f"The driver did not start ({last}). Check the dongle is "
                              "plugged in with an OTG adapter and try again.")
        return None

    async def _sdr_stop(self) -> None:
        src, self.sdr_source = self.sdr_source, None
        if self.sdr_task is not None:
            self.sdr_task.cancel()
            self.sdr_task = None
        if src is not None:
            await self._run(src.close)
        self.sdr_btn.text = "Start"
        self.sdr_info.text = "Stopped."

    async def _sdr_loop(self) -> None:
        from bosun import dsp

        frames = 0
        while self.sdr_source is not None:
            src = self.sdr_source
            try:
                iq = await self._run(src.read, 16384)
                off, p = dsp.psd(iq, src.rate, 2048)
                dets = self.cog.process(off, p, src.center_hz)
                self.fall.push(off + src.center_hz, p)
                png = self.fall.png(dets, self.sdr_selected)
                self.sdr_view.image = toga.Image(src=png)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.sdr_info.text = f"SDR error: {exc}"
                await self._sdr_stop()
                return
            frames += 1
            if frames % 5 == 0:
                self._sdr_refresh_table(dets)
            await asyncio.sleep(0.15)

    def _sdr_refresh_table(self, dets) -> None:
        sigs = self.cog.ranked()[:40]
        self._sdr_rows = sigs
        self.sdr_table.data = [(f"{s.center_hz / 1e6:.4f}", s.kind,
                                f"{s.best_snr_db:.0f} dB", f"{s.activity:.0%}")
                               for s in sigs]
        src = self.sdr_source
        if src is not None:
            self.sdr_info.text = (f"{src.name}  {src.center_hz / 1e6:.4f} MHz  "
                                  f"{len(dets)} signal(s) now, {len(self.cog.signals)} logged")

    async def _sdr_pick(self, widget) -> None:
        row_ = widget.selection
        if row_ is None:
            return
        try:
            idx = widget.data.index(row_)
            sig = self._sdr_rows[idx]
        except Exception:
            return
        self.sdr_selected = sig.center_hz
        self.freq.value = f"{sig.center_hz / 1e6:.5f}"
        self.sdr_info.text = f"{sig.center_hz / 1e6:.5f} MHz: {sig.kind}. {sig.hint}."
        if self.ctl.connected and not self.ctl.audio_only:
            try:
                st = await self._run(self.ctl.tune, self.freq.value, None)
                self.status.value = format_status(st)
                self.sdr_info.text += " Radio tuned."
            except Exception as exc:
                self.sdr_info.text += f" Radio: {exc}"

    async def _sdr_retune(self, widget) -> None:
        from bosun.control import parse_mhz

        if self.sdr_source is None:
            return
        try:
            hz = parse_mhz(self.sdr_center.value)
            await self._run(self.sdr_source.tune, hz)
            self.cog.reset()
        except Exception as exc:
            self.sdr_info.text = f"Error: {exc}"

    async def _sdr_gain(self, widget) -> None:
        if self.sdr_source is not None:
            try:
                await self._run(self.sdr_source.set_gain, float(widget.value))
            except Exception as exc:
                self.sdr_info.text = f"Gain: {exc}"

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
