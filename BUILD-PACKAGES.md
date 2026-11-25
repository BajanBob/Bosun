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
- **Sweep** ranges wider than one view and log what is found.
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
