"""CLI: `frameshot` -> instant capture (via daemon if warm)."""

from __future__ import annotations

import argparse
import sys

# Must stay identical to frameshot.app.SERVER_NAME (duplicated, not imported:
# importing frameshot.app pulls Qt, which is exactly what the hot path avoids).
SERVER_NAME = "frameshot-daemon-v1"


def _fast_ping(timeout: float = 0.5) -> bool:
    """Ping the warm daemon over its unix socket — no Qt, no imports.

    This is the entire hotkey fast path: stdlib socket connect + 8 bytes.
    ~1ms vs ~80ms for the old throwaway-QApplication ping.
    """
    import os
    import socket
    import tempfile
    tried = []
    for tmp in dict.fromkeys([tempfile.gettempdir(), "/tmp"]):
        path = os.path.join(tmp, SERVER_NAME)
        tried.append(path)
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(path)
            s.sendall(b"capture\n")
            s.close()
            return True
        except OSError:  # noqa: BLE001
            continue
    # stale socket file from a dead daemon: clear it so next start binds clean
    for path in tried:
        try:
            if os.path.exists(path):
                import stat as _stat
                if _stat.S_ISSOCK(os.stat(path).st_mode):
                    os.unlink(path)
        except OSError:  # noqa: BLE001
            pass
    return False


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="frameshot",
        description="Wayland-native screenshot + annotate + OCR (clipboard-first).")
    ap.add_argument("--daemon", action="store_true",
                    help="Run warm daemon for instant hotkey launches.")
    ap.add_argument("--stop", action="store_true",
                    help="Stop the background service (and login autostart).")
    ap.add_argument("--no-daemon", action="store_true",
                    help="Skip daemon fast-path even if it is running.")
    ap.add_argument("--version", action="store_true", help="Print version.")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("capture", help="Capture -> select -> annotate (default).")
    sub.add_parser("doctor", help="Diagnose the screenshot pipeline.")
    sub.add_parser("settings", help="Open the GUI settings page.")
    cfg = sub.add_parser("config", help="Show config path/values.")
    cfg.add_argument("--show", action="store_true")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        from . import __version__
        print(__version__)
        return 0
    if args.daemon:
        from .app import run_daemon
        return run_daemon()
    if args.stop:
        from . import background as bg
        was_running = bg.daemon_running()
        bg.stop_daemon()
        had_autostart = bg.autostart_enabled()
        bg.set_autostart(False)
        if was_running or had_autostart:
            print("frameshot background service stopped"
                  + (" (login autostart disabled)" if had_autostart else "")
                  + ".")
        else:
            print("frameshot background service is not running.")
        print("Start again any time: open frameshot → gear → Start, "
              "or run `frameshot --daemon &`.")
        return 0
    if args.cmd == "settings":
        from PyQt6.QtWidgets import QApplication
        from .config import FrameshotSettings, default_config_dir
        from .overlay import SettingsDialog
        app = QApplication.instance() or QApplication([])
        s = FrameshotSettings.load()
        dlg = SettingsDialog(s)
        if dlg.exec():
            dlg.apply()
            print(f"Settings saved to {default_config_dir() / 'settings.ini'}")
        return 0
    if args.cmd == "doctor":
        from .doctor import run
        return run()
    if args.cmd == "config":
        from .config import FrameshotSettings, default_config_dir
        s = FrameshotSettings.load()
        print(f"config: {default_config_dir() / 'settings.ini'}")
        print(f"save_to_disk={s.save_to_disk} save_dir={s.save_dir} "
              f"format={s.image_format} ocr={s.ocr_engine}/{s.ocr_lang} "
              f"hotkey={s.hotkey} "
              f"portal_interactive_fallback={s.portal_interactive_fallback}")
        return 0
    # default: capture (fast path first -> pointer #1). Raw-socket ping
    # keeps this path Qt-free: interpreter + argparse + ~1ms of socket.
    if not args.no_daemon and _fast_ping():
        return 0
    from .app import run_capture_flow
    return run_capture_flow()


if __name__ == "__main__":
    sys.exit(main())
