"""Offscreen tests: OCR popup cursors/clicks/placement + toolbar icons."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtTest import QTest

from frameshot import icons as _icons
from frameshot.config import FrameshotSettings
from frameshot.overlay import FrameshotOverlay


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _overlay(app, sel=QRect(150, 150, 400, 300)):
    full = QPixmap(800, 600)
    full.fill(QColor("#808080"))
    ov = FrameshotOverlay(full, FrameshotSettings())
    ov.resize(800, 600)
    ov.show()
    app.processEvents()
    ov.sel = QRect(sel)
    ov._place_bar()
    ov.ocr_btn.setChecked(True)
    app.processEvents()
    return ov


def _copy_button(ov):
    for b in ov.popup.findChildren(QPushButton):
        if b.text() == "Copy text":
            return b
    raise AssertionError("Copy text button missing")


def test_popup_widgets_do_not_show_crosshair(app):
    """No crosshair anywhere in the OCR popup (it looked dead)."""
    ov = _overlay(app)
    assert ov.popup.isVisible()
    assert ov.popup.cursor().shape() != Qt.CursorShape.CrossCursor
    btn = _copy_button(ov)
    assert btn.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert ov.ocr_text.viewport().cursor().shape() == Qt.CursorShape.IBeamCursor
    ov.close()


def test_copy_button_click_copies(app, monkeypatch):
    """Clicking Copy text copies the popup text."""
    import frameshot.clipboard as clipmod

    calls = []
    monkeypatch.setattr(clipmod, "copy_text_to_clipboard",
                        lambda t: calls.append(t) or True)
    ov = _overlay(app)
    ov.ocr_text.setPlainText("hello ocr")
    QTest.mouseClick(_copy_button(ov), Qt.MouseButton.LeftButton)
    app.processEvents()
    assert calls == ["hello ocr"]
    assert "copied" in ov.ocr_status.text().lower()
    ov.close()


def test_popup_avoids_toolbar_when_room(app):
    """Snip mid-screen: popup sits fully on-screen, clear of the toolbar."""
    ov = _overlay(app, QRect(150, 150, 400, 300))
    pg, og = ov.popup.geometry(), ov.rect()
    assert og.contains(pg), pg.getRect()
    assert not pg.intersects(ov.bar.geometry()), (
        pg.getRect(), ov.bar.geometry().getRect())
    ov.close()


def test_popup_stays_onscreen_when_crowded(app, monkeypatch):
    """Snip low on screen: popup stays inside the overlay and Copy still works."""
    import frameshot.clipboard as clipmod

    calls = []
    monkeypatch.setattr(clipmod, "copy_text_to_clipboard",
                        lambda t: calls.append(t) or True)
    ov = _overlay(app, QRect(50, 500, 300, 150))
    pg, og = ov.popup.geometry(), ov.rect()
    assert og.contains(pg), pg.getRect()
    btn = _copy_button(ov)
    assert btn.isVisible()
    ov.ocr_text.setPlainText("crowded ocr")
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert calls == ["crowded ocr"]
    ov.close()


def test_toolbar_icons_render():
    """Every toolbar icon produces a non-null pixmap."""
    for name in ("move", "rect", "ellipse", "arrow", "line", "pen", "text",
                 "blur", "undo", "redo", "ocr", "copy", "save", "close",
                 "check", "gear"):
        assert not _icons.icon(name, 22).pixmap(22, 22).isNull(), name
