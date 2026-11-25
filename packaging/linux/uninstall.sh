#!/usr/bin/env sh
set -eu
rm -f "$HOME/.local/bin/Bosun" "$HOME/.local/bin/bosun-cli" \
  "$HOME/.local/share/applications/bosun.desktop" \
  "$HOME/.local/share/icons/hicolor/256x256/apps/bosun.png"
echo "Bosun removed."
