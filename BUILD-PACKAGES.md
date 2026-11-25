# Bosun packages

`.github/workflows/package.yml` builds every package on each push to `main`,
on version tags (`v*`), and from Actions → Build Bosun Packages → Run workflow.

| Artifact | File | What it is |
|---|---|---|
| `Bosun-windows` | `Bosun-Windows-x64.zip` | Portable: `Bosun.exe` (desktop app) + `bosun-cli.exe` |
| `Bosun-windows` | `Bosun-Windows-Desktop-Setup.exe` | Installer: Start menu + desktop shortcut, per-user, no admin rights |
| `Bosun-linux` | `Bosun-Linux-x86_64.zip` / `.tar.gz` | `Bosun` (desktop app), `bosun-cli`, `install.sh` adds it to the app menu |
| `Bosun-android` | `Bosun-Mobile-Android.apk` | Bosun Mobile (debug-signed, sideload) |

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
- **Hover tips** on every control (Help → Show hover tips to switch off).

## Notes

- Windows: builds are not code-signed, so SmartScreen may warn on first run
  ("More info" → "Run anyway"). RTL-SDR dongles need the WinUSB driver once
  (install it with Zadig).
- Linux: extract, then run `./install.sh`. USB serial needs the `dialout` group
  (`uucp` on Arch); RTL-SDR may need the `rtl-sdr` udev rules from your distro.
- Android: network (TCP) radio control only; install by allowing "Install
  unknown apps".
- Barrett / Harris: Bosun does not guess their command sets. Copy the commands
  from the radio's remote-control (RS-232) manual into the wizard's command
  profile; it is saved in your settings folder under `radio_profiles`.
