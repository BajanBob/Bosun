# Bosun packages

`.github/workflows/package.yml` builds every package on each push to `main`,
on version tags (`v*`), and from Actions → Build Bosun Packages → Run workflow.

| Artifact | File | What it is |
|---|---|---|
| `Bosun-windows` | `Bosun-Windows-x64.zip` | Portable: `Bosun.exe` (desktop app) + `bosun-cli.exe` |
| `Bosun-windows` | `Bosun-Windows-Desktop-Setup.exe` | Installer: Start menu + desktop shortcut, per-user, no admin rights |
| `Bosun-linux` | `Bosun-Linux-x86_64.zip` / `.tar.gz` | `Bosun` (desktop app), `bosun-cli`, `install.sh` adds it to the app menu |
| `Bosun-android` | `Bosun-Mobile-Android.apk` | Bosun Mobile: radio control, RTL-SDR spectrum + signal detection (debug-signed, sideload) |

## What the desktop app does

- **Setup wizard** on first run (and Setup → Setup wizard): pick maker and
  model, connect, choose an SDR and audio input, test, save.
- **Radios**: Icom (CI-V), Yaesu and Kenwood (CAT), AOR, built in. Barrett and
  Harris through a command profile you fill in once from the radio's
  remote-control manual. Radtel RT-950 Pro: no PC control, so audio capture and
  CHIRP channel export.
- **Spectrum**: RTL-SDR (driver bundled), SoapySDR devices, Airspy, or the
  built-in Demo. Live spectrum + waterfall, hover readout, click to tune the
  radio, double-click to re-centre.
- **Automatic signal detection** with plain-language labels (CW, SSB, AM, FM,
  broadcast, wideband...), and a **cognitive receiver** that learns the noise
  floor, logs every signal with how busy it is, and flags new ones.
- **Wide spans**: an RTL-SDR streams about 2.4 MHz at once (its hardware
  limit). The 5 / 10 / 20 / 40 MHz "(sweep)" spans step it across the range
  and stitch one live picture (slower refresh; recording needs 2.4 MHz or
  less). **Sweep** covers any range and logs what is found.
- **Live listening** (the receive > DSP > demodulator > speaker chain): click a
  signal, press Listen; FM / WFM / AM / USB / LSB / CW, squelch, volume,
  de-emphasis; follows whatever you click. The Audio tab can also play the
  radio's own audio through the speakers. Faceplate: LISTEN key.
- **SSTV pictures** (Pictures tab): Martin, Scottie, Robot 36, PD90/120/180
  (ISS events use PD120/PD180 on 145.800 MHz) from the radio's audio, an SDR
  signal or a WAV file; pictures save automatically. (NOAA APT weather
  satellites were switched off in 2025, so APT is not included.)
- **Analogue video** (View > Video): PAL / NTSC black-and-white pictures from
  FPV (FM, 5.8 GHz Raceband / Band A, 1.3 GHz) or broadcast (AM). Needs a wide
  receiver: the HackRF One (up to 20 MS/s) via the standard `hackrf_transfer`
  tool, which you install once (Great Scott Gadgets release, PothosSDR, or your
  package manager). A built-in test pattern lets you try it without hardware.
  Snapshot PNG and video recording.
- **Video recording**: spectrum/waterfall, faceplate (REC) and analogue video.
  MP4 when ffmpeg is installed, otherwise AVI (Motion JPEG) which plays in VLC
  and Windows Media Player.
- **Second screen** (View > Second screen): faceplate, spectrum or video full
  screen on another monitor or TV.
- **Recording**: IQ (SigMF), demodulated audio (WAV), radio audio from any sound
  input (WAV), spectrum screen captures (PNG). Saved in `Bosun Recordings` in
  your home folder.
- **Automatic device detection**: plug a radio in and Bosun asks the new port
  who is there (Yaesu / Kenwood `ID;`, Icom CI-V at each known address, at the
  usual baud rates), then offers to connect. Unplugging disconnects cleanly.
  A newly plugged-in SDR gets a "Show spectrum" offer. Programming cables
  (CH340 / Prolific, e.g. Radtel) are recognised and pointed to the Audio tab.
  Also Setup > Detect my radio now, and "Detect my radio" in the wizard.
  Turn off under Help > Watch for plugged-in radios and SDRs.
- **Faceplate** (View > Faceplate, or the "Bosun Faceplate" shortcut, or
  `Bosun --faceplate --full-screen`): a touch-screen front panel in green and
  gold with a big ON button, large frequency display (swipe to tune), step and
  mode keys, live spectrum (tap to tune), cognitive signal tiles (tap to tune;
  AUTO follows the busiest signal, SCAN hops through them) and a red night
  viewing mode that keeps your eyes dark-adapted.
- **Hover tips** on every control (Help → Show hover tips to switch off).

## Notes

- Windows: builds are not code-signed, so SmartScreen may warn on first run
  ("More info" → "Run anyway"). RTL-SDR dongles need the WinUSB driver once
  (install it with Zadig).
- Linux: extract, then run `./install.sh`. USB serial needs the `dialout` group
  (`uucp` on Arch); RTL-SDR may need the `rtl-sdr` udev rules from your distro.
- Android: install by allowing "Install unknown apps". Radio control is over
  the network (TCP).
- Android RTL-SDR: plug the dongle in with a USB OTG adapter and install the
  free open-source "Rtl-sdr driver" app by Martin Marinov (`marto.rtl_tcp_andro`,
  F-Droid or Play Store). In Bosun Mobile choose SDR > "RTL-SDR on this phone"
  and Start; Bosun launches the driver, Android asks for USB permission, and
  the spectrum, waterfall and signal list appear. Bosun Mobile also notices
  when a dongle is plugged in and offers to start the spectrum. Tap a signal to tune the
  connected radio. "rtl_tcp on the network" reads a dongle on a PC or
  Raspberry Pi running `rtl_tcp -a 0.0.0.0`.
- Desktop rtl_tcp: type `rtl_tcp:host:port` as the spectrum source.
- Barrett / Harris: Bosun does not guess their command sets. Copy the commands
  from the radio's remote-control (RS-232) manual into the wizard's command
  profile; it is saved in your settings folder under `radio_profiles`.
