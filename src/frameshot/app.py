"""Application orchestration + instant-launch daemon (pointer #1).

Cold start cost is python + Qt import (~200-400ms). The daemon
(`frameshot --daemon`) keeps a warm QApplication so `frameshot` (hotkey) can show the
overlay in <50ms via a QLocalSocket ping.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QPixmap
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox

SERVER_NAME = "frameshot-daemon-v1"


def ensure_app(argv=None) -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv or [])
        app.setApplicationName("frameshot")
        app.setOrganizationName("frameshot")
    return app  # type: ignore[return-value]


def normalize_selection_for_pixmap(sel: QRect, overlay_geo, pix: QPixmap) -> QRect:
    """Map overlay-widget coords to pixmap pixels (handles scaling)."""
    if overlay_geo.width() <= 0 or overlay_geo.height() <= 0:
        return sel
    sx = pix.width() / overlay_geo.width()
    sy = pix.height() / overlay_geo.height()
    return QRect(int(sel.x() * sx), int(sel.y() * sy),
                 int(sel.width() * sx), int(sel.height() * sy))


def run_capture_flow(settings=None) -> int:
    """Single-stage flow: fullscreen overlay (select + annotate + copy)."""
    from PyQt6.QtGui import QPixmap

    from .capture import capture_png_bytes_ex, qt_fallback_pixmap
    from .config import FrameshotSettings
    from .overlay import FrameshotOverlay

    settings = settings or FrameshotSettings.load()
    app = ensure_app(sys.argv)

    via_interactive = False
    try:
        data, via_interactive = capture_png_bytes_ex(
            portal_interactive_fallback=settings.portal_interactive_fallback)
        full = QPixmap()
        if not full.loadFromData(data, "PNG"):
            raise RuntimeError("Failed to decode captured screenshot.")
    except Exception as e:  # noqa: BLE001
        # Fallback so `QT_QPA_PLATFORM=offscreen frameshot` still smokes.
        try:
            full = qt_fallback_pixmap()
            if full.isNull():
                raise RuntimeError(str(e))
        except Exception:
            QMessageBox.critical(None, "frameshot", f"Screenshot failed:\n{e}")
            return 1

    overlay = None
    if via_interactive:
        # Image was already composed in the compositor's screenshot UI —
        # single stage, preselected, straight to annotate.
        overlay = FrameshotOverlay(full, settings, preselect_full=True)
        overlay.setGeometry(app.primaryScreen().geometry())
        overlay._bg = full
        overlay.showFullScreen()
        overlay._layout_chrome()
        while overlay.isVisible():
            app.processEvents()
            QThread_msleep(10)
        return 0

    from .overlay import StageSession
    session = StageSession()
    screens = app.screens()
    if not screens:
        raise RuntimeError("No screens available.")
    union = screens[0].geometry()
    for s in screens[1:]:
        union = union.united(s.geometry())
    # Source pixels per logical pixel (uniform across outputs; mixed-DPI
    # setups are approximately right, exactly right when uniform).
    scale = full.width() / union.width() if union.width() else 1.0
    # Stitched source + virtual geometry: lets a snip span outputs.
    session.set_source(full, union)
    for scr in screens:
        geo = scr.geometry()
        rel = geo.translated(-union.topLeft())
        px_rect = QRect(int(rel.x() * scale), int(rel.y() * scale),
                        int(rel.width() * scale),
                        int(rel.height() * scale)).intersected(full.rect())
        crop = full.copy(px_rect) if px_rect.isValid() else full
        ov = FrameshotOverlay(crop, settings)
        ov.origin = rel.topLeft()
        session.add(ov)
        ov.show_on_screen(scr)
    while session.any_visible():
        app.processEvents()
        QThread_msleep(10)
    return 0


def QThread_msleep(ms: int):
    from PyQt6.QtCore import QThread
    QThread.msleep(ms)


def try_daemon_ping() -> bool:
    """Ping warm daemon. Returns True if daemon accepted a capture request."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(b"capture\n")
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def run_daemon() -> int:
    """Warm process: preload Qt + hold single-instance server."""
    from .config import FrameshotSettings
    app = ensure_app(sys.argv)
    # Critical: the default True makes QApplication.quit() fire when the
    # capture overlay closes — which silently kills the daemon right after
    # its FIRST capture (every later hotkey then falls back to a cold,
    # unprivileged launch and fails). A daemon must outlive its windows.
    app.setQuitOnLastWindowClosed(False)
    # Pre-import heavy Qt modules so hotkey path is pure overlay.
    import frameshot.overlay  # noqa: F401

    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    if not server.listen(SERVER_NAME):
        print(f"frameshot daemon: cannot listen: {server.errorString()}",
              file=sys.stderr)
        return 1
    print("frameshot daemon ready (hotkey -> `frameshot`). Ctrl+C to stop.")

    def on_conn():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        sock.waitForReadyRead(500)
        cmd = bytes(sock.readAll()).decode(errors="ignore").strip()
        sock.disconnectFromServer()
        if cmd in ("capture", ""):
            settings = FrameshotSettings.load()
            # Run flow without nesting app.exec: reuse same process.
            run_capture_flow(settings)

    server.newConnection.connect(on_conn)
    return app.exec()
