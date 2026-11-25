#!/usr/bin/env sh
# Installs Bosun for the current user and adds it to the applications menu.
set -eu
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$BIN" "$APPS" "$ICONS"
install -m 755 "$HERE/Bosun" "$BIN/Bosun"
install -m 755 "$HERE/bosun-cli" "$BIN/bosun-cli"
install -m 644 "$HERE/bosun.png" "$ICONS/bosun.png"
sed "s|^Exec=Bosun|Exec=$BIN/Bosun|" "$HERE/bosun.desktop" > "$APPS/bosun.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" || true
echo "Bosun installed. Open it from your applications menu."
if ! id -nG | grep -qwE "dialout|uucp"; then
  echo "For USB serial radios, add yourself to the serial group, then log out and in:"
  echo "  sudo usermod -aG dialout \"$USER\"   (Arch: uucp)"
fi
