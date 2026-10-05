"""Background service, login autostart, and global-hotkey management.

Honest limitation, stated once: on Wayland no app can grab global hotkeys
itself — the keybinding always lives in the compositor. What frameshot *can* do
from its Settings page:
  - run/stop the warm `frameshot --daemon` background service,
  - toggle login autostart for it,
  - read/write the GNOME custom keybinding that summons `frameshot`
    (other compositors: show the one-line config snippet to copy).

gi (PyGObject) is imported lazily so plain `frameshot` startup stays fast.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

GNOME_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_CHILD = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
FRAMESHOT_DPATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/frameshot/"
DEFAULT_BINDING = "<Primary><Shift>f"  # Ctrl+Shift+F (spec default)
SUGGESTED_BINDING = "<Primary><Shift>g"  # conflict-free fallback (grab)
FRAMESHOT_CMD = "frameshot"


def frameshot_cmd_abs() -> str:
    """Absolute binary path — keybinding launchers often lack ~/.local/bin."""
    found = shutil.which("frameshot")
    if found:
        return found
    local = Path.home() / ".local/bin/frameshot"
    if local.exists():
        return str(local)
    return sys.argv[0]


# -- daemon ---------------------------------------------------------------
def _frameshot_bin() -> str:
    if shutil.which("frameshot"):
        return "frameshot"
    return sys.argv[0]


def _daemon_pids() -> list[int]:
    """PIDs of running `frameshot --daemon`, matched precisely via /proc.

    (Deliberately not `pgrep -f`: a substring match would hit the very
    shell running `frameshot --stop` when its command line mentions --daemon.)
    """
    found: list[int] = []
    me = os.getpid()
    try:
        for pid in filter(str.isdigit, os.listdir("/proc")):
            if int(pid) == me:
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    raw = f.read().split(b"\0")
            except (FileNotFoundError, PermissionError):
                continue
            parts = [a for a in raw if a]
            if len(parts) >= 2 and parts[-1] == b"--daemon" and (
                    parts[-2] == b"frameshot" or parts[-2].endswith(b"/frameshot")):
                found.append(int(pid))
    except FileNotFoundError:
        pass  # not Linux — no daemon support
    return found


def daemon_running() -> bool:
    return bool(_daemon_pids())


# -- autostart: systemd user service (preferred) --------------------------
# `frameshot-daemon.service` survives reboots, restarts on failure, and runs in
# a stable cgroup (so portal permission grants apply to it). The legacy
# ~/.config/autostart/frameshot-daemon.desktop path is still honored for status.

SERVICE = "frameshot-daemon.service"


def _systemctl(*args: str) -> bool:
    try:
        p = subprocess.run(["systemctl", "--user", *args],
                           capture_output=True, timeout=15)
        return p.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def autostart_path() -> Path:
    return (Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            / "autostart" / "frameshot-daemon.desktop")


def _service_file() -> Path:
    return (Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            / "systemd" / "user" / SERVICE)


def autostart_enabled() -> bool:
    if _service_file().exists():
        try:
            p = subprocess.run(
                ["systemctl", "--user", "is-enabled", SERVICE],
                capture_output=True, text=True, timeout=10)
            if p.returncode == 0:
                return True
        except Exception:  # noqa: BLE001
            pass
        return False
    return autostart_path().exists()


def set_autostart(on: bool) -> bool:
    try:
        if _service_file().exists():
            ok = _systemctl("enable" if on else "disable", SERVICE)
            if on:
                _systemctl("start", SERVICE)
            return ok
        # legacy fallback: plain autostart desktop file
        p = autostart_path()
        if on:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                "[Desktop Entry]\n"
                "Name=frameshot background service\n"
                "Comment=Warm frameshot process for instant hotkey screenshots\n"
                f"Exec={_frameshot_bin()} --daemon\n"
                "Icon=frameshot\n"
                "Terminal=false\n"
                "Type=Application\n"
                "Categories=Utility;\n"
                "NoDisplay=true\n"
                "X-GNOME-Autostart-enabled=true\n")
        elif p.exists():
            p.unlink()
        return True
    except Exception:  # noqa: BLE001
        return False


def start_daemon() -> bool:
    if daemon_running():
        return True
    if _service_file().exists() and _systemctl("start", SERVICE):
        return True
    try:
        subprocess.Popen([_frameshot_bin(), "--daemon"],
                         start_new_session=True,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
        return True
    except Exception:  # noqa: BLE001
        return False


def stop_daemon() -> None:
    _systemctl("stop", SERVICE)
    import signal
    for pid in _daemon_pids():
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


# -- GNOME hotkey (via Gio.Settings, no subprocess) ----------------------
def _settings():
    import gi  # type: ignore
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio  # type: ignore
    return Gio


def gnome_available() -> bool:
    try:
        Gio = _settings()
        s = Gio.Settings.new(GNOME_SCHEMA)
        s.get_strv("custom-keybindings")
        return True
    except Exception:  # noqa: BLE001
        return False


def gnome_binding() -> tuple[str | None, str | None]:
    """Return (binding, command) of frameshot's GNOME hotkey, or (None, None)."""
    Gio = _settings()
    s = Gio.Settings.new(GNOME_SCHEMA)
    if FRAMESHOT_DPATH not in list(s.get_strv("custom-keybindings")):
        return None, None
    c = Gio.Settings.new_with_path(GNOME_CHILD, FRAMESHOT_DPATH)
    return c.get_string("binding") or None, c.get_string("command") or None


def set_gnome_binding(binding: str, command: str | None = None) -> None:
    Gio = _settings()
    s = Gio.Settings.new(GNOME_SCHEMA)
    lst = list(s.get_strv("custom-keybindings"))
    if FRAMESHOT_DPATH not in lst:
        lst.append(FRAMESHOT_DPATH)
        s.set_strv("custom-keybindings", lst)
    c = Gio.Settings.new_with_path(GNOME_CHILD, FRAMESHOT_DPATH)
    c.set_string("name", "frameshot screenshot")
    c.set_string("command", command or frameshot_cmd_abs())
    c.set_string("binding", binding)
    Gio.Settings.sync()


def _norm_binding(b: str) -> str:
    mods, keys = [], []
    for part in b.replace("><", "> <").replace("<", "").replace(">", " ").split():
        p = part.strip().lower()
        if p in ("primary", "ctrl", "control"):
            mods.append("ctrl")
        elif p in ("shift", "alt", "super", "meta", "hyper"):
            mods.append(p)
        elif p:
            keys.append(p)
    return "+".join(sorted(set(mods)) + keys)


def list_custom_bindings() -> list[tuple[str, str, str, str]]:
    """[(dpath, name, binding, command)] for every GNOME custom keybinding."""
    Gio = _settings()
    s = Gio.Settings.new(GNOME_SCHEMA)
    out = []
    for path in s.get_strv("custom-keybindings"):
        try:
            c = Gio.Settings.new_with_path(GNOME_CHILD, path)
            out.append((path, c.get_string("name") or "",
                        c.get_string("binding") or "",
                        c.get_string("command") or ""))
        except Exception:  # noqa: BLE001
            continue
    return out


def find_binding_conflicts(binding: str, ignore_frameshot: bool = True
                           ) -> list[tuple[str, str, str]]:
    """Other actions already using this combo: [(dpath, name, command)]."""
    want = _norm_binding(binding)
    hits = []
    for path, name, other, cmd in list_custom_bindings():
        if ignore_frameshot and path == FRAMESHOT_DPATH:
            continue
        if other and _norm_binding(other) == want:
            hits.append((path, name, cmd))
    return hits


def clear_gnome_binding() -> None:
    Gio = _settings()
    s = Gio.Settings.new(GNOME_SCHEMA)
    lst = [p for p in s.get_strv("custom-keybindings") if p != FRAMESHOT_DPATH]
    s.set_strv("custom-keybindings", lst)
    c = Gio.Settings.new_with_path(GNOME_CHILD, FRAMESHOT_DPATH)
    c.reset("name")
    c.reset("command")
    c.reset("binding")
    Gio.Settings.sync()


def compositor_hint() -> str:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    if "GNOME" in desktop:
        return ""
    if "KDE" in desktop:
        return ("KDE: System Settings → Shortcuts → Custom Shortcuts → "
                "New → command `frameshot` → assign Ctrl+Shift+F.")
    if "sway" in desktop.lower() or "Hyprland" in desktop:
        which = "sway" if "sway" in desktop.lower() else "hypr"
        if which == "sway":
            return ("Sway (~/.config/sway/config):\n"
                    "    bindsym Control+Shift+f exec frameshot")
        return ("Hyprland (~/.config/hypr/hyprland.conf):\n"
                "    bind = CTRL SHIFT, F, exec, frameshot")
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return ("Your compositor owns global hotkeys — bind one to `frameshot`:\n"
                "Sway: bindsym Control+Shift+f exec frameshot\n"
                "Hyprland: bind = CTRL SHIFT, F, exec, frameshot")
    return ""
