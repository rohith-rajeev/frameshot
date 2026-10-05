#!/usr/bin/env bash
# frameshot uninstaller — removes everything install.sh / setup-hotkey.sh created.
#
# Usage:
#   bash scripts/uninstall.sh [--dry-run] [--yes] [--keep-config] [--remove-screenshots]
#
#   --dry-run            print what would be removed, change nothing
#   --yes                skip confirmation prompts (keeps screenshots unless
#                        --remove-screenshots is also given)
#   --keep-config        keep ~/.config/frameshot/settings.ini
#   --remove-screenshots also delete ~/Pictures/frameshot (your saved shots)
#
# What is removed:
#   - running `frameshot --daemon` / open frameshot windows
#   - ~/.local/bin/frameshot symlink
#   - ~/.local/share/applications/frameshot.desktop
#   - GNOME custom keybinding .../custom-keybindings/frameshot/ (other apps' bindings untouched)
#   - GNOME Shell extension frameshot-capture@frameshot.local (disable + remove dir)
#   - ~/.config/autostart/frameshot*.desktop (only if you added the daemon there)
#   - <repo>/.venv (the editable install)
#   - ~/.config/frameshot (unless --keep-config)
#   - ~/Pictures/frameshot (only with --remove-screenshots)
#
# NOT touched (may be shared with other apps):
#   system packages (grim, wl-clipboard, tesseract, python3-gi).
# Manual compositor lines (Sway/Hyprland/KDE) must be deleted by hand — see
# the reminder printed at the end.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"

DRY_RUN=0
ASSUME_YES=0
KEEP_CONFIG=0
REMOVE_SHOTS=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes) ASSUME_YES=1 ;;
    --keep-config) KEEP_CONFIG=1 ;;
    --remove-screenshots) REMOVE_SHOTS=1 ;;
    -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 1 ;;
  esac
done

run() {  # run <desc> <cmd...>: echo in dry-run, execute otherwise
  local desc="$1"; shift
  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] would $desc: $*"
  else
    echo "$desc..."
    "$@" || true
  fi
}

ask() {  # ask <prompt>: true if yes (auto-yes with --yes)
  if [ "$ASSUME_YES" = 1 ] || [ "$DRY_RUN" = 1 ]; then
    return 0
  fi
  local ans
  read -r -p "$1 [y/N] " ans || true
  [[ "${ans:-}" =~ ^[Yy]$ ]]
}

echo "frameshot uninstaller (repo: $REPO)"
[ "$DRY_RUN" = 1 ] && echo "--- DRY RUN: nothing will be changed ---"

# 1. Stop warm daemon / open frameshot windows (precise match; won't touch mutter-x11-frames etc.)
if pgrep -f "[f]rame --daemon" >/dev/null 2>&1; then
  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] would stop: $(pgrep -af "[f]rame --daemon" | cut -c1-100)"
  else
    echo "Stopping frameshot daemon..."
    pkill -f "[f]rame --daemon" || true
  fi
else
  echo "No frameshot daemon running."
fi
if pgrep -f "[.]venv/bin/frameshot" >/dev/null 2>&1; then
  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] would stop: $(pgrep -af "[.]venv/bin/frameshot" | cut -c1-100)"
  else
    echo "Closing open frameshot windows..."
    pkill -f "[.]venv/bin/frameshot" || true
  fi
fi

# 1b. Background service (systemd unit + legacy autostart file)
if [ "$DRY_RUN" = 1 ]; then
  echo "[dry-run] would stop/disable/remove frameshot-daemon.service + autostart file"
else
  systemctl --user stop frameshot-daemon.service 2>/dev/null || true
  systemctl --user disable frameshot-daemon.service 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/frameshot-daemon.service"
  rm -f "$HOME/.config/autostart/frameshot-daemon.desktop"
  echo "Background service removed."
fi

# 2. ~/.local/bin/frameshot symlink (only if it belongs to frameshot)
BIN_LINK="$HOME/.local/bin/frameshot"
if [ -L "$BIN_LINK" ]; then
  target="$(readlink "$BIN_LINK")"
  case "$target" in
    *frameshot*) run "remove symlink $BIN_LINK -> $target" rm -f "$BIN_LINK" ;;
    *) echo "WARNING: $BIN_LINK points to $target (not frameshot) — left alone." ;;
  esac
elif [ -e "$BIN_LINK" ]; then
  echo "WARNING: $BIN_LINK exists but is not a symlink — left alone."
else
  echo "No $BIN_LINK."
fi

# 3. Desktop file (only if it is ours)
DESKTOP_FILE="$HOME/.local/share/applications/frameshot.desktop"
if [ -f "$DESKTOP_FILE" ]; then
  if grep -qi "frameshot" "$DESKTOP_FILE"; then
    run "remove $DESKTOP_FILE" rm -f "$DESKTOP_FILE"
  else
    echo "WARNING: $DESKTOP_FILE doesn't mention frameshot — left alone."
  fi
else
  echo "No $DESKTOP_FILE."
fi

# 3b. App icons (only frameshot's own)
for icon in "$HOME/.local/share/icons/hicolor/scalable/apps/frameshot.svg" \
            "$HOME/.local/share/icons/hicolor/256x256/apps/frameshot.png"; do
  if [ -f "$icon" ]; then
    run "remove icon $icon" rm -f "$icon"
  fi
done
if [ "$DRY_RUN" = 0 ]; then
  gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor 2>/dev/null || true
fi

# 4. GNOME custom keybinding — remove ONLY our entry, keep everyone else's
GBASE="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
GFRAMESHOT="${GBASE}/frameshot/"
if command -v gsettings >/dev/null 2>&1 && \
   gsettings list-schemas 2>/dev/null | grep -q "org.gnome.settings-daemon.plugins.media-keys"; then
  current="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null || echo "[]")"
  if [[ "$current" == *"$GFRAMESHOT"* ]]; then
    new_list="$(python3 - " $GFRAMESHOT" <<'EOF'
import sys
path = sys.argv[1]
try:
    lst = eval(sys.stdin.read().strip() or "[]")
except Exception:
    lst = []
lst = [p for p in lst if p != path]
print(str(lst).replace("'", "'"))
EOF
    <<<"$current")"
    if [ "$DRY_RUN" = 1 ]; then
      echo "[dry-run] would remove GNOME binding $GFRAMESHOT (keeping: $new_list)"
    else
      echo "Removing GNOME hotkey binding..."
      gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$new_list" || true
      gsettings reset-recursively "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:${GFRAMESHOT}" || true
    fi
  else
    echo "No GNOME frameshot hotkey binding."
  fi
else
  echo "gsettings/GNOME schema not present — skipping hotkey cleanup."
fi

# 4b. GNOME Shell extension (disable + remove our dir only)
EXT_UUID="frameshot-capture@frameshot.local"
EXT_DIR="$HOME/.local/share/gnome-shell/extensions/$EXT_UUID"
if [ -d "$EXT_DIR" ]; then
  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] would disable + remove GNOME extension $EXT_UUID"
  else
    echo "Disabling GNOME extension $EXT_UUID..."
    gnome-extensions disable "$EXT_UUID" 2>/dev/null || true
    CUR="$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null || echo "@as []")"
    CLEAN="${CUR#@as }"
    NEW="$(python3 -c "
import ast
lst = ast.literal_eval('''${CLEAN:-[]}'''.strip() or '[]')
lst = [u for u in lst if u != '$EXT_UUID']
print(lst)
" 2>/dev/null || echo "$CLEAN")"
    gsettings set org.gnome.shell enabled-extensions "$NEW" 2>/dev/null || true
    rm -rf "$EXT_DIR"
  fi
else
  echo "No GNOME extension $EXT_UUID."
fi

# 5. Autostart entries (only frameshot's own)
shopt -s nullglob
for f in "$HOME/.config/autostart/"frameshot*.desktop; do
  if grep -qi "frameshot" "$f"; then
    run "remove autostart entry $f" rm -f "$f"
  else
    echo "WARNING: $f doesn't mention frameshot — left alone."
  fi
done
shopt -u nullglob

# 6. Repo venv (the editable install itself)
if [ -d "$REPO/.venv" ]; then
  run "remove repo venv $REPO/.venv" rm -rf "$REPO/.venv"
else
  echo "No $REPO/.venv."
fi

# 7. Settings
CONFIG_DIR="$HOME/.config/frameshot"
if [ "$KEEP_CONFIG" = 1 ]; then
  echo "Keeping $CONFIG_DIR (--keep-config)."
elif [ -d "$CONFIG_DIR" ]; then
  run "remove config $CONFIG_DIR" rm -rf "$CONFIG_DIR"
else
  echo "No $CONFIG_DIR."
fi

# 8. Screenshots — user data, never deleted silently
SHOTS_DIR="$HOME/Pictures/frameshot"
if [ -d "$SHOTS_DIR" ]; then
  if [ "$REMOVE_SHOTS" = 1 ]; then
    if ask "Delete your saved screenshots in $SHOTS_DIR?"; then
      run "remove screenshots $SHOTS_DIR" rm -rf "$SHOTS_DIR"
    else
      echo "Keeping $SHOTS_DIR."
    fi
  else
    echo "Keeping your screenshots in $SHOTS_DIR (pass --remove-screenshots to delete)."
  fi
else
  echo "No $SHOTS_DIR."
fi

cat <<'EOF'

--- manual leftovers (if you added them by hand) ---
Sway (~/.config/sway/config):            delete the `bindsym ... exec frameshot` line
Hyprland (~/.config/hypr/hyprland.conf): delete the `bind = ..., exec, frameshot` line
KDE Settings -> Shortcuts:               delete the custom `frameshot` entry
GNOME Startup Apps:                      remove `frameshot --daemon` if you added it

To delete this repo too:  rm -rf <repo-dir>
System packages (grim, wl-clipboard, tesseract, python3-gi) were left installed.
EOF
[ "$DRY_RUN" = 1 ] && echo "--- DRY RUN complete: nothing was changed ---"
echo "frameshot uninstalled."
