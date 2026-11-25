# Bosun packages

`.github/workflows/package.yml` builds every package on each push to `main`,
on version tags (`v*`), and from Actions → Build Bosun Packages → Run workflow.

| Artifact | File | What it is |
|---|---|---|
| `Bosun-windows` | `Bosun-Windows-x64.zip` | Portable: `Bosun.exe` (desktop app) + `bosun-cli.exe` |
| `Bosun-windows` | `Bosun-Windows-Desktop-Setup.exe` | Installer: Start menu + desktop shortcut, per-user, no admin rights |
| `Bosun-linux` | `Bosun-Linux-x86_64.tar.gz` | `Bosun` (desktop app), `bosun-cli`, `install.sh` adds it to the app menu |
| `Bosun-android` | `Bosun-Mobile-Android.apk` | Bosun Mobile (debug-signed, sideload) |

The desktop app connects over **USB serial** (COM port / `/dev/ttyUSB*`) or the
**network** (TCP, e.g. ser2net). It covers tuning, mode, AF/RF/squelch levels,
status, range scanning and device discovery.

Each platform's binary must be built on that platform.

## Notes

- Windows: builds are not code-signed, so SmartScreen may warn on first run
  ("More info" → "Run anyway").
- Linux: extract, then run `./install.sh`. For USB serial, your user must be in
  the `dialout` group (`uucp` on Arch).
- Android: network (TCP) only for now; install by allowing "Install unknown
  apps". A Play Store release needs a signed AAB.
