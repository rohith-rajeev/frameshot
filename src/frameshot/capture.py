"""Fullscreen capture backends for Wayland (and X11 fallback).

Wayland forbids arbitrary screen reads, so frameshot captures the fullscreen
image *first* (fast native tool), then shows the flameshot-style overlay on
top of that image (pointer #2). Chain (first success wins):

1. frameshot's own GNOME Shell extension (in-compositor capture, silent —
   no portal, no dialog). Requires the extension installed + enabled.
2. grim (wlroots: Sway/Hyprland/Wayfire/river) — fastest, no dialog
3. XDG Screenshot portal, non-interactive (GNOME/KDE/wlroots — the
   sanctioned Wayland path, no dialog). Retried once: gnome-shell
   transiently refuses with response=2 from time to time.
4. XDG Screenshot portal, interactive (compositor's native UI) —
   only as a last resort before giving up, and only when explicitly
   enabled (settings.portal_interactive_fallback, default OFF — frameshot
   never pops another tool's UI uninvited). The returned image
   is already user-composed, so frameshot skips its own selection overlay.
5. KDE spectacle
6. GNOME Shell screenshot D-Bus (legacy, blocked on GNOME 40+)
7. Qt fallback (works for testing; often blank for other apps on Wayland)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


class PortalError(RuntimeError):
    """Screenshot-portal failure with the numeric response code attached."""

    def __init__(self, message: str, response: int | None = None):
        super().__init__(message)
        self.response = response


class ExtensionMissing(RuntimeError):
    """frameshot's GNOME Shell helper is absent (fast skip, not a failure)."""


def _shell_extension_capture(timeout: int = 15) -> bytes:
    """Fullscreen PNG via frameshot's own GNOME Shell extension.

    The extension (shell-extension/frameshot-capture@frameshot.local) runs inside
    the compositor and captures exactly like GNOME's own screenshot
    facility — no portal, no consent dialog, no foreign UI.
    Raises ExtensionMissing immediately when the bus name is unowned.
    """
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
    if not owned.unpack()[0]:
        raise ExtensionMissing(
            "frameshot GNOME Shell extension not installed/enabled "
            "(see shell-extension/ + install.sh).")
    res = bus.call_sync(
        "org.frameshot.Capture", "/org/frameshot/Capture", "org.frameshot.Capture",
        "Screenshot", None, GLib.VariantType("(bs,)"),
        Gio.DBusCallFlags.NONE, max(5, timeout) * 1_000, None)
    ok, path = res.unpack()
    if not ok:
        raise RuntimeError(f"frameshot shell extension capture failed: {path}")
    with open(path, "rb") as f:
        data = f.read()
    try:
        os.unlink(path)
    except OSError:  # noqa: BLE001
        pass
    if not data[:8].startswith(b"\x89PNG"):
        raise RuntimeError("frameshot shell extension did not return a PNG.")
    return data


def _portal_close(bus, req_path: str) -> None:
    """Best-effort Request.Close — dismisses pending dialogs, frees server state."""
    try:
        bus.call_sync(
            "org.freedesktop.portal.Desktop", req_path,
            "org.freedesktop.portal.Request", "Close", None, None,
            0, 3_000, None)
    except Exception:  # noqa: BLE001
        pass


def _portal_capture(timeout: int = 30, interactive: bool = False) -> bytes:
    """Screenshot via org.freedesktop.portal.Screenshot (Gio, lazy import).

    This is the sanctioned Wayland path: works on GNOME (where direct
    org.gnome.Shell.Screenshot calls are denied with 'Screenshot is not
    allowed'), KDE, and wlroots. Non-interactive mode shows no dialog;
    interactive mode shows the compositor's native screenshot UI and is
    used only as an explicit fallback. Requires PyGObject
    (python3-gi on Debian/Ubuntu).
    """
    import random

    import gi  # type: ignore

    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib  # type: ignore

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    unique = bus.get_unique_name().lstrip(":").replace(".", "_")
    token = f"frameshot{os.getpid()}{random.randint(0, 999999)}"
    req_path = f"/org/freedesktop/portal/desktop/request/{unique}/{token}"

    state: dict = {}

    def on_response(_conn, _sender, obj_path, _iface, _sig, params, _ud):
        if obj_path == req_path:
            state["response"] = (params[0], params[1])
            state["loop"].quit()

    sub = bus.signal_subscribe(
        "org.freedesktop.portal.Desktop",
        "org.freedesktop.portal.Request",
        "Response",
        req_path,
        None,
        Gio.DBusSignalFlags.NO_MATCH_RULE,
        on_response,
        None,
    )
    try:
        proxy = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Screenshot",
            None,
        )
        options = GLib.Variant("a{sv}", {
            "handle_token": GLib.Variant("s", token),
            "modal": GLib.Variant("b", False),
            "interactive": GLib.Variant("b", interactive),
        })
        try:
            args = GLib.Variant.new_tuple(
                GLib.Variant("s", ""), options)
            proxy.call_sync(
                "Screenshot", args,
                Gio.DBusCallFlags.NONE, 10_000, None)
        except Exception as e:  # noqa: BLE001
            raise PortalError(f"portal Screenshot call failed: {e}")

        loop = GLib.MainLoop()
        state["loop"] = loop

        def on_timeout():
            state.setdefault("timed_out", True)
            loop.quit()
            return False  # don't repeat

        GLib.timeout_add_seconds(max(5, timeout), on_timeout)
        loop.run()

        if state.get("timed_out") or "response" not in state:
            raise PortalError(
                "portal Screenshot timed out waiting for a response. "
                "If a consent dialog appeared ('Share this screenshot'), "
                "allow it and try again.")
        code, results = state["response"]
        if code == 1:
            raise PortalError("portal Screenshot was cancelled.", response=1)
        if code != 0:
            raise PortalError(
                f"portal Screenshot failed (response={code}). "
                "On GNOME this usually means screenshot permission was "
                "denied: run `frameshot doctor`, or allow screenshots in "
                "Settings → Apps, then try again.",
                response=code,
            )
        uri = results.get("uri")
        if not uri:
            raise PortalError("portal Screenshot returned no URI.")
        path = urllib.parse.urlparse(uri).path
        path = urllib.request.url2pathname(path)
        with open(path, "rb") as f:
            data = f.read()
        try:
            os.unlink(path)
        except OSError:  # noqa: BLE001
            pass
        if not data[:8].startswith(b"\x89PNG"):
            raise PortalError("portal Screenshot did not return a PNG.")
        return data
    finally:
        try:
            if "response" in state or state.get("timed_out"):
                _portal_close(bus, req_path)
        except Exception:  # noqa: BLE001
            pass
        try:
            bus.signal_unsubscribe(sub)
        except Exception:  # noqa: BLE001
            pass


def _portal_capture_noninteractive(timeout: int, attempts: int = 2) -> bytes:
    """Non-interactive portal capture with one retry (fresh token each try).

    gnome-shell transiently answers response=2 on some calls; a single
    immediate retry recovers without bothering the user.
    """
    last: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            return _portal_capture(timeout=timeout, interactive=False)
        except PortalError as e:
            last = e
            if e.response == 1:  # user cancelled — don't retry
                raise
    assert last is not None
    raise last


def capture_png_bytes_ex(timeout: int = 15,
                           portal_interactive_fallback: bool = True
                           ) -> tuple[bytes, bool]:
    """Capture fullscreen; returns (png_bytes, via_interactive_portal).

    via_interactive_portal=True means the image was already composed by the
    user in the compositor's screenshot UI — callers should skip their own
    selection step and go straight to annotate.
    """
    errors: list[str] = []

    # 1. frameshot's own GNOME Shell extension (in-compositor, silent, no portal)
    try:
        return _shell_extension_capture(timeout=timeout), False
    except ImportError as e:
        errors.append(f"shell-extension rung unavailable (python3-gi): {e}")
    except ExtensionMissing as e:
        errors.append(f"shell extension: {e}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"shell extension failed: {e}")

    # 2. grim
    if _which("grim"):
        try:
            p = subprocess.run(
                ["grim", "-t", "png", "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            if p.returncode == 0 and p.stdout[:8].startswith(b"\x89PNG"):
                return p.stdout
            errors.append(f"grim failed: {p.stderr.decode()[:200]}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"grim error: {e}")

    # 3. XDG Screenshot portal, non-interactive (sanctioned Wayland path)
    try:
        return _portal_capture_noninteractive(timeout=timeout), False
    except ImportError as e:
        errors.append(f"portal unavailable (pip/apt install PyGObject/python3-gi): {e}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"portal failed: {e}")

    # 4. XDG Screenshot portal, interactive (compositor's native UI).
    # Only when nothing silent worked: guarantees a result on GNOME even
    # when non-interactive capture is denied. The image is user-composed,
    # so the caller skips its own selection overlay (flagged via True).
    if portal_interactive_fallback:
        try:
            return _portal_capture(timeout=timeout, interactive=True), True
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001
            errors.append(f"portal interactive failed: {e}")

    # 5. KDE spectacle
    if _which("spectacle"):
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tmp = tf.name
            p = subprocess.run(
                ["spectacle", "-b", "-n", "-o", tmp],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                with open(tmp, "rb") as f:
                    data = f.read()
                os.unlink(tmp)
                if data[:8].startswith(b"\x89PNG"):
                    return data
            errors.append(f"spectacle failed: {p.stderr.decode()[:200]}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"spectacle error: {e}")

    # 6. GNOME Shell D-Bus screenshot (legacy; denied on GNOME 40+)
    if _which("gdbus"):
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tmp = tf.name
            p = subprocess.run(
                [
                    "gdbus", "call", "--session",
                    "--dest", "org.gnome.Shell",
                    "--object-path", "/org/gnome/Shell/Screenshot",
                    "--method", "org.gnome.Shell.Screenshot.Screenshot",
                    "false", "false", tmp,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                with open(tmp, "rb") as f:
                    data = f.read()
                os.unlink(tmp)
                return data
            errors.append(f"gnome screenshot failed: {p.stderr.decode()[:200]}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"gnome screenshot error: {e}")

    # 7. gnome-screenshot legacy
    if _which("gnome-screenshot"):
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tmp = tf.name
            p = subprocess.run(
                ["gnome-screenshot", "-f", tmp],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                with open(tmp, "rb") as f:
                    data = f.read()
                os.unlink(tmp)
                return data
            errors.append(f"gnome-screenshot failed: {p.stderr.decode()[:200]}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"gnome-screenshot error: {e}")

    raise RuntimeError(
        "No screenshot backend worked. On GNOME this usually means the "
        "XDG portal call failed — run `frameshot doctor` to diagnose "
        "(screenshot permission, portal services). Details: "
        + " | ".join(errors)
    )


def capture_png_bytes(timeout: int = 15) -> bytes:
    """Return fullscreen PNG bytes (non-interactive backends only).

    Interactive portal UI is never triggered here — pass
    portal_interactive_fallback=True via capture_png_bytes_ex to allow it.
    """
    data, _ = capture_png_bytes_ex(
        timeout=timeout, portal_interactive_fallback=False)
    return data


def capture_qpixmap():
    """Capture fullscreen and return a QPixmap (imports Qt lazily for speed)."""
    from PyQt6.QtGui import QPixmap

    data = capture_png_bytes()
    px = QPixmap()
    if not px.loadFromData(data, "PNG"):
        raise RuntimeError("Failed to decode captured screenshot.")
    return px


def qt_fallback_pixmap():
    """Last-resort grab via Qt (used in tests / offscreen)."""
    from PyQt6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen()
    if screen is None:
        raise RuntimeError("No screen available.")
    return screen.grabWindow(0)
