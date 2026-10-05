"""Clipboard helpers. Pointer #5: copy image to clipboard by default."""

from __future__ import annotations

import shutil
import subprocess


def copy_qimage_to_clipboard(qimage) -> bool:
    """Copy a QImage/QPixmap to the system clipboard. Returns True on success."""
    from PyQt6.QtGui import QGuiApplication

    cb = QGuiApplication.clipboard()
    cb.setImage(qimage)
    return True


def copy_text_to_clipboard(text: str) -> bool:
    from PyQt6.QtGui import QGuiApplication

    cb = QGuiApplication.clipboard()
    cb.setText(text)
    # Best-effort wl-copy persist on Wayland so clipboard survives app exit.
    if shutil.which("wl-copy"):
        try:
            subprocess.run(["wl-copy"], input=text.encode(),
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
        except Exception:  # noqa: BLE001
            pass
    return True


def persist_image_via_wlcopy(png_bytes: bytes) -> bool:
    """Best-effort: push PNG bytes via wl-copy (helps some Wayland compositors)."""
    if not shutil.which("wl-copy"):
        return False
    try:
        subprocess.run(["wl-copy", "--type", "image/png"],
                       input=png_bytes, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)
        return True
    except Exception:  # noqa: BLE001
        return False
