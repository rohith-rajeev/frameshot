#!/usr/bin/env bash
# frameshot hotkey setup — default Ctrl+Shift+F (pointer #1).
# Wayland has no portable in-app global hotkeys, so the compositor must call `frameshot`.
set -euo pipefail
HOTKEY="${FRAMESHOT_HOTKEY:-${FRAME_HOTKEY:-<Primary><Shift>f}}"  # FRAME_HOTKEY = pre-rename
echo "Setting up frameshot hotkey (default Ctrl+Shift+F)..."

setup_gnome() {
  local base="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
  local path="${base}/frameshot/"
  gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings \
    "$(python3 - " $path" <<'EOF'
import json, subprocess, sys
path = sys.argv[1]
try:
    cur = subprocess.check_output(["gsettings","get","org.gnome.settings-daemon.plugins.media-keys","custom-keybindings"], text=True)
except Exception:
    cur = "[]"
try:
    lst = eval(cur.strip()) if cur.strip() not in ("@as []","[]","") else []
except Exception:
    lst = []
if path not in lst:
    lst.append(path)
print(str(lst).replace("'", "'"))
EOF
)"
  gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${path}" name 'frameshot screenshot' || true
  # Absolute path: keybinding launchers often lack ~/.local/bin on PATH.
  _frameshot_bin="$(command -v frameshot || echo "$HOME/.local/bin/frameshot")"
  gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${path}" command "$_frameshot_bin" || true
  gsettings set "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${path}" binding "${HOTKEY}" || true
  echo "GNOME: bound ${HOTKEY} -> frameshot"
}

if command -v gsettings >/dev/null 2>&1 && [ "${XDG_CURRENT_DESKTOP:-}" != "KDE" ]; then
  if gsettings list-schemas 2>/dev/null | grep -q "org.gnome.settings-daemon.plugins.media-keys"; then
    setup_gnome || true
  fi
fi

cat <<'EOF'

--- compositor snippets (if GNOME step above did not apply) ---

Sway (~/.config/sway/config):
    bindsym Control+Shift+f exec frameshot

Hyprland (~/.config/hypr/hyprland.conf):
    bind = CTRL SHIFT, F, exec, frameshot

KDE: System Settings -> Shortcuts -> Custom -> New -> `frameshot` -> Ctrl+Shift+F

Autostart warm daemon (instant open, pointer #1):
    frameshot --daemon &
  Add to GNOME Startup Apps / sway `exec frameshot --daemon` / Hyprland `exec-once = frameshot --daemon`.

Needs: grim (wlroots) OR spectacle (KDE) OR GNOME shell; wl-clipboard for persistent clipboard.
  sudo apt install grim wl-clipboard tesseract-ocr   # paddleocr optional: pip install "frameshot[ocr-paddle]"
EOF
