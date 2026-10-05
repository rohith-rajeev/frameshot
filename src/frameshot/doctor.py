"""`frameshot doctor` — diagnose the screenshot pipeline.

Checks: session type, PyGObject, shell extension (installed/enabled/live),
portal service, permission-store entry, and backend binaries.
All checks are read-only.
"""

from __future__ import annotations

import os
import shutil


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _portal_reachable() -> bool:
    """True if org.freedesktop.portal.Desktop owns a bus name."""
    try:
        import gi  # type: ignore
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio  # type: ignore
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None,
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Screenshot", None)
        return bool(proxy.get_name_owner())
    except Exception:  # noqa: BLE001
        return False


def _extension_status() -> str:
    """Check frameshot's GNOME Shell extension: dir, enabled, bus live."""
    from pathlib import Path

    uuid = "frameshot-capture@frameshot.local"
    d = Path.home() / ".local/share/gnome-shell/extensions" / uuid
    if not d.is_dir():
        return "not installed (run install.sh; needs one logout/login)"
    enabled = "unknown"
    try:
        import subprocess
        out = subprocess.run(["gnome-extensions", "list", "--enabled"],
                             capture_output=True, text=True, timeout=10)
        enabled = ("enabled" if uuid in out.stdout.split()
                   else "installed but DISABLED")
    except Exception:  # noqa: BLE001
        pass
    live = "bus name absent"
    try:
        import gi  # type: ignore
        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib  # type: ignore
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        owned = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "NameHasOwner",
            GLib.Variant("(s)", ("org.frameshot.Capture",)),
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE, 3_000, None)
        live = ("LIVE on session bus" if owned.unpack()[0]
                else "not loaded (log out/in after enabling?)")
    except Exception:  # noqa: BLE001
        pass
    return f"installed, {enabled}, {live}"


def _permission_entry() -> str:
    """Read-only lookup of the screenshot permission table."""
    try:
        import gi  # type: ignore
        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib  # type: ignore
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        res = bus.call_sync(
            "org.freedesktop.impl.portal.PermissionStore",
            "/org/freedesktop/impl/portal/PermissionStore",
            "org.freedesktop.impl.portal.PermissionStore",
            "Lookup",
            GLib.Variant("(ss)", ("screenshot", "screenshot")),
            None, Gio.DBusCallFlags.NONE, 5_000, None)
        return str(res.unpack()[0])
    except Exception as e:  # noqa: BLE001
        return f"(unreadable: {e})"


def run() -> int:
    print(f"session: {os.environ.get('XDG_SESSION_TYPE', '?')} "
          f"desktop={os.environ.get('XDG_CURRENT_DESKTOP', '?')}")
    try:
        import gi  # type: ignore  # noqa: F401
        print("PyGObject (gi): available")
    except ImportError:
        print("PyGObject (gi): MISSING — portal backend disabled. "
              "Fix: sudo apt install python3-gi (and use install.sh's venv).")
    if _portal_reachable():
        print("screenshot portal bus: reachable")
    else:
        print("screenshot portal bus: NOT reachable "
              "(is xdg-desktop-portal running?)")
    print(f"gnome shell extension: {_extension_status()}")
    print(f"screenshot permission store: {_permission_entry()}")
    print("  ('yes' for '' = unsandboxed apps allowed. If it shows 'no' or "
          "'ask', allow screenshots in Settings → Apps, or re-run a capture "
          "from a terminal and accept the consent dialog.)")
    for tool, who in (("grim", "wlroots"), ("spectacle", "KDE"),
                      ("gdbus", "GNOME dbus"), ("gnome-screenshot", "legacy"),
                      ("tesseract", "OCR fallback"), ("wl-copy", "clipboard")):
        print(f"{tool} ({who}): {'present' if _have(tool) else 'absent'}")
    try:
        from .background import list_custom_bindings, FRAMESHOT_DPATH
        print("GNOME custom hotkeys:")
        for path, name, binding, cmd in list_custom_bindings():
            mark = "  <-- frameshot" if path == FRAMESHOT_DPATH else ""
            print(f"  {binding or '(none)'} -> {name or path} [{cmd}]{mark}")
    except Exception as e:  # noqa: BLE001
        print(f"GNOME custom hotkeys: unreadable ({e})")
    try:
        import importlib.util as _ilu
        print(f"paddleocr: {'installed' if _ilu.find_spec('paddleocr') else 'absent'}; "
              f"cv2: {'installed' if _ilu.find_spec('cv2') else 'absent'} "
              f"(need both for paddle OCR: pip install 'frameshot[ocr-paddle]')")
    except Exception:  # noqa: BLE001
        pass
    return 0
