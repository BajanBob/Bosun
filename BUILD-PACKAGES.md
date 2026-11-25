# Bosun packages

Bosun is a command-line radio-control application. The Windows desktop
package adds a double-click launcher, not a GUI. Bosun Mobile (Android) is a
small touch front end for tuning, status and range scanning.

## Automated builds

`.github/workflows/package.yml` runs on every push to `main`, on version tags
(`v*`), and from Actions → Build Bosun Desktop Packages → Run workflow.

| Artifact | File | Contents |
|---|---|---|
| `Bosun-windows` | `Bosun-Windows-x64.zip` | standalone `Bosun.exe` |
| `Bosun-windows` | `Bosun-Windows-Desktop.zip` | `Bosun.exe` + double-click launcher |
| `Bosun-linux` | `Bosun-Linux-x86_64.tar.gz` | standalone executable + launcher |
| `Bosun-android` | `Bosun-Mobile-Android.apk` | Bosun Mobile (debug-signed, sideload) |

Each platform's binary must be built on that platform; do not rename one
platform's build as another's.

## Android notes

- The APK connects to radios **over the network** (TCP): use ser2net, a
  LAN-to-serial adapter or a Wi-Fi serial bridge attached to the radio's CAT
  port. Direct USB-serial from the phone is not supported yet.
- The APK is debug-signed. Install it by allowing "Install unknown apps" for
  your browser or file manager. A Play Store release needs a signed AAB
  (`briefcase package android` with your own keystore).
- Build locally: `pip install briefcase && briefcase create android && briefcase build android`.
