# Bosun executable packages

The project is currently a command-line radio-control application. The
Windows desktop package adds a double-click launcher, but it is not a GUI.

## Automated native builds

GitHub Actions workflow `.github/workflows/package.yml` builds native
standalone packages on Windows and Linux. Run it from Actions → Build desktop
packages → Run workflow, or push a version tag (`v*`). The resulting artifacts
are named `Bosun-windows` and `Bosun-linux`.

- Windows executable: `Bosun-Windows-x64.zip` (standalone Bosun.exe)
- Windows desktop: `Bosun-Windows-Desktop.zip` (Bosun.exe + desktop launcher)
- Linux: `Bosun-Linux-x86_64.tar.gz` (standalone executable + launcher)

The Windows executable must be built on Windows and the Linux executable on
Linux; do not rename one platform's binary as the other platform's build.
