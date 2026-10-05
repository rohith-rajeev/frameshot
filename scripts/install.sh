#!/usr/bin/env bash
# frameshot installer: venv + pip install + desktop file + optional hotkey.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-/usr/bin/python3}"
echo "Using $PY ($($PY --version 2>&1))"
$PY -m venv --system-site-packages .venv
# NOTE: --system-site-packages is intentional: frameshot's Wayland screenshot
# backend uses PyGObject (python3-gi, shipped by the distro — `sudo apt
# install python3-gi gir1.2-glib-2.0` if missing) which pip cannot provide.
.venv/bin/pip install -U pip
.venv/bin/pip install -e ".[ocr-tesseract]"
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/frameshot" ~/.local/bin/frameshot
ln -sf "$PWD/.venv/bin/frame" ~/.local/bin/frame 2>/dev/null || true  # pre-rename alias
mkdir -p ~/.local/share/applications
sed "s|^Exec=frameshot|Exec=$HOME/.local/bin/frameshot|" assets/frameshot.desktop > ~/.local/share/applications/frameshot.desktop
rm -f ~/.local/share/applications/frame.desktop  # pre-rename leftover
# Minimal app icon (SVG + raster), replaces the stock camera-photo icon.
mkdir -p ~/.local/share/icons/hicolor/scalable/apps ~/.local/share/icons/hicolor/256x256/apps
cp assets/frameshot.svg ~/.local/share/icons/hicolor/scalable/apps/frameshot.svg
cp assets/frameshot-256.png ~/.local/share/icons/hicolor/256x256/apps/frameshot.png
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor 2>/dev/null || true
echo "Installed: ~/.local/bin/frameshot (ensure ~/.local/bin is on PATH)"
echo "Optional OCR (heavy, lazy-loaded): .venv/bin/pip install -e '.[ocr-paddle]'"
read -r -p "Set up Ctrl+Shift+F hotkey now? [y/N] " ans || true
if [[ "${ans:-}" =~ ^[Yy]$ ]]; then
  bash scripts/setup-hotkey.sh
fi

# GNOME Shell extension: frameshot's own in-compositor capturer. Silent
# screenshots with no portal and no consent dialogs. Needs one logout/login
# (or `gnome-extensions enable` triggering a shell reload) to take effect.
EXT_UUID="frameshot-capture@frameshot.local"
OLD_UUID="frame-capture@frame.local"  # pre-rename extension: remove on upgrade
if [ "${XDG_CURRENT_DESKTOP:-}" = *GNOME* ] || command -v gnome-extensions >/dev/null 2>&1; then
  mkdir -p ~/.local/share/gnome-shell/extensions
  if [ -d ~/.local/share/gnome-shell/extensions/"$OLD_UUID" ]; then
    gnome-extensions disable "$OLD_UUID" 2>/dev/null || true
    rm -rf ~/.local/share/gnome-shell/extensions/"$OLD_UUID"
    echo "Removed pre-rename extension $OLD_UUID."
  fi
  rm -rf ~/.local/share/gnome-shell/extensions/"$EXT_UUID"
  cp -r "shell-extension/$EXT_UUID" ~/.local/share/gnome-shell/extensions/
  # `gnome-extensions enable` rejects freshly copied dirs ("does not exist")
  # until the shell rescans, so append to enabled-extensions directly.
  if ! gnome-extensions enable "$EXT_UUID" 2>/dev/null; then
    CUR="$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null || echo "@as []")"
    CLEAN="${CUR#@as }"
    NEW="$(python3 -c "
import ast
lst = ast.literal_eval('''${CLEAN:-[]}'''.strip() or '[]')
if '$EXT_UUID' not in lst:
    lst.append('$EXT_UUID')
print(lst)
" 2>/dev/null || echo "['$EXT_UUID']")"
    gsettings set org.gnome.shell enabled-extensions "$NEW" 2>/dev/null || true
  fi
  echo "GNOME extension $EXT_UUID installed + enabled."
  echo "NOTE: log out and back in once so GNOME Shell loads it."
else
  echo "Not GNOME — skipping shell extension."
fi

# Background service: automatic by default — no manual daemon wrangling.
# A systemd user service (stable cgroup, restart-on-failure, starts at login).
# `frameshot --stop` opts back out.
# Drop the pre-rename unit so two daemons never run side by side.
systemctl --user stop frame-daemon.service 2>/dev/null || true
systemctl --user disable frame-daemon.service 2>/dev/null || true
rm -f ~/.config/systemd/user/frame-daemon.service ~/.config/autostart/frame-daemon.desktop
mkdir -p ~/.config/systemd/user
sed -e "s|@HOME@|$HOME|" \
    -e "s|@WAYLAND@|${WAYLAND_DISPLAY:-wayland-0}|" \
    -e "s|@DISPLAY@|${DISPLAY:-:0}|" \
    -e "s|@RUNTIME@|${XDG_RUNTIME_DIR:-/run/user/$(id -u)}|" \
    assets/frameshot-daemon.service > ~/.config/systemd/user/frameshot-daemon.service
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable --now frameshot-daemon.service 2>/dev/null || \
  (setsid "$HOME/.local/bin/frameshot" --daemon >/dev/null 2>&1 < /dev/null &) || true
echo "Background service enabled (starts at login + running now). Stop it with: frameshot --stop"
