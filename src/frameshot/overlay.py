"""Single-stage capture flow (flameshot-style).

One fullscreen window does everything: drag to snip, then annotate in the
same place — no second window. A floating glass toolbar carries tools,
colors, undo, OCR, save/copy/close; OCR appears in a popup above the snip.
Export = selection crop + annotations, clipboard-first.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from PyQt6.QtCore import (Qt, QRect, QRectF, QPoint, QPointF, QEvent,
                           QSize, QSizeF, QBuffer, QIODevice, QTimer)
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QPixmap, QFont, QFontMetricsF, QCursor,
    QAction, QRegion, QPolygonF, QTransform,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QTextEdit, QPlainTextEdit, QLineEdit, QSlider, QFileDialog, QMessageBox, QInputDialog,
    QDialog, QFormLayout, QCheckBox, QApplication, QToolButton, QFrame,
)

from . import icons as _icons

ACCENT = "#0a84ff"
GLASS = "rgba(28,28,32,232)"
TOOLBAR_QSS = f"""
QWidget#bar {{ background: {GLASS}; border-radius: 14px;
  border: 1px solid rgba(255,255,255,28); }}
QToolButton {{ background: transparent; border: none; border-radius: 8px;
  color: white; }}
QToolButton:hover {{ background: rgba(255,255,255,26); }}
QToolButton:checked {{ background: {ACCENT}; }}
QToolButton#primary {{ background: {ACCENT}; border-radius: 8px; font-weight: bold; }}
QToolButton#primary:hover {{ background: #3395ff; }}
QToolButton:disabled {{ color: rgba(255,255,255,90); }}
QSlider::groove:horizontal {{ height: 4px; background: rgba(255,255,255,40);
  border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 12px; height: 12px; background: white;
  border-radius: 6px; margin: -4px 0; }}
QLabel#dim {{ color: rgba(255,255,255,170); }}
"""
CARD_QSS = f"""
QWidget#card {{ background: {GLASS}; border-radius: 14px;
  border: 1px solid rgba(255,255,255,28); }}
QPushButton {{ background: rgba(255,255,255,22); color: white;
  border: none; border-radius: 8px; padding: 6px 10px; }}
QPushButton:hover {{ background: rgba(255,255,255,40); }}
QPushButton#go {{ background: {ACCENT}; font-weight: bold; }}
QTextEdit, QComboBox, QLineEdit {{ background: rgba(0,0,0,120); color: white;
  border: 1px solid rgba(255,255,255,40); border-radius: 8px; }}
QLabel {{ color: white; }}
"""


class Tool(Enum):
    MOVE = auto()
    RECT = auto()
    ELLIPSE = auto()
    ARROW = auto()
    LINE = auto()
    PEN = auto()
    TEXT = auto()
    BLUR = auto()


@dataclass
class Shape:
    kind: Tool
    p1: QPoint = field(default_factory=QPoint)
    p2: QPoint = field(default_factory=QPoint)
    points: list = field(default_factory=list)
    text: str = ""
    color: str = "#ff3b30"
    width: int = 3
    font_size: int = 18
    angle: float = 0.0  # text rotation, degrees clockwise


COLORS = ["#ff3b30", "#ff9500", "#ffcc00", "#34c759",
          "#0a84ff", "#bf5af2", "#ffffff", "#000000"]
WIDTHS = [2, 3, 5, 8, 12]


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("frameshot — settings")
        self.setStyleSheet(CARD_QSS)
        form = QFormLayout(self)
        self.save_disk = QCheckBox("Save a copy to disk (default: clipboard only)")
        self.save_disk.setChecked(settings.save_to_disk)
        self.save_dir = QLineEdit(settings.save_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.save_dir)
        row.addWidget(browse)
        wrap = QWidget()
        wrap.setLayout(row)
        self.fmt = QComboBox()
        self.fmt.addItems(["png", "jpg"])
        self.fmt.setCurrentText(settings.image_format)
        self.ocr_engine = QComboBox()
        self.ocr_engine.addItems(["auto", "paddle", "tesseract", "off"])
        self.ocr_engine.setCurrentText(settings.ocr_engine)
        self.ocr_lang = QLineEdit(settings.ocr_lang)
        self.interactive_fb = QCheckBox("If silent capture is denied, use system screenshot UI")
        self.interactive_fb.setChecked(settings.portal_interactive_fallback)
        form.addRow(self.save_disk)
        form.addRow("Save folder:", wrap)
        form.addRow("Format:", self.fmt)
        form.addRow("OCR engine:", self.ocr_engine)
        form.addRow("OCR lang:", self.ocr_lang)
        form.addRow(self.interactive_fb)
        self._build_background_section(form)
        self._build_hotkey_section(form)
        self._build_version_section(form)
        btns = QHBoxLayout()
        ok = QPushButton("Save")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        form.addRow(btns)

    def _build_background_section(self, form):
        from . import background as _bg
        self._bg = _bg
        self.daemon_status = QLabel()
        self.daemon_btn = QPushButton()
        self.daemon_btn.clicked.connect(self._toggle_daemon)
        drow = QHBoxLayout()
        drow.addWidget(self.daemon_status)
        drow.addWidget(self.daemon_btn)
        dwrap = QWidget()
        dwrap.setLayout(drow)
        form.addRow("Background service:", dwrap)
        self.autostart_box = QCheckBox("Launch at login (instant hotkey)")
        self.autostart_box.setChecked(_bg.autostart_enabled())
        form.addRow(self.autostart_box)
        self._refresh_daemon()

    def _refresh_daemon(self):
        running = self._bg.daemon_running()
        self.daemon_status.setText("running" if running else "stopped")
        self.daemon_btn.setText("Stop" if running else "Start now")

    def _toggle_daemon(self):
        if self._bg.daemon_running():
            self._bg.stop_daemon()
        else:
            self._bg.start_daemon()
        QTimer.singleShot(600, self._refresh_daemon)

    def _build_version_section(self, form):
        from . import __version__
        self._update_worker = None
        self.version_label = QLabel(f"frameshot v{__version__}")
        self.update_btn = QPushButton("Check for updates")
        self.update_btn.clicked.connect(self._check_updates)
        self.update_status = QLabel("")
        self.update_status.setWordWrap(True)
        vrow = QHBoxLayout()
        vrow.addWidget(self.version_label)
        vrow.addWidget(self.update_btn)
        vwrap = QWidget()
        vwrap.setLayout(vrow)
        form.addRow("Version:", vwrap)
        form.addRow(self.update_status)

    def _check_updates(self):
        from . import __version__
        from .updates import UpdateCheckWorker
        self.update_btn.setEnabled(False)
        self.update_status.setText("Checking…")
        self._update_worker = UpdateCheckWorker(__version__, self)
        self._update_worker.done.connect(self._update_result)
        self._update_worker.failed.connect(self._update_failed)
        self._update_worker.start()

    def _update_failed(self, err: str):
        self.update_btn.setEnabled(True)
        self.update_status.setText(f"Update check failed: {err}")

    def _update_result(self, rel: dict):
        from . import __version__
        from . import updates as _up
        self.update_btn.setEnabled(True)
        if not rel.get("is_newer"):
            self.update_status.setText(
                f"You're on the latest version (v{__version__}).")
            return
        tag = rel.get("tag", "")
        notes = (rel.get("body") or "")[:400]
        from PyQt6.QtWidgets import QMessageBox, QProgressDialog
        from PyQt6.QtCore import Qt as _Qt
        box = QMessageBox(self)
        box.setWindowTitle("frameshot update")
        box.setText(f"Version {tag} is available (you have v{__version__}).")
        box.setInformativeText((notes + "\n\nDownload and install now?"
                                if notes else
                                "Download and install now?"))
        box.setStandardButtons(QMessageBox.StandardButton.Yes |
                               QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            self.update_status.setText(f"Staying on v{__version__}.")
            return
        prog = QProgressDialog("Downloading + installing…", "Cancel",
                               0, 0, self)
        prog.setWindowModality(_Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        try:
            asset = _up.pick_asset(rel)
            if asset is None:
                raise RuntimeError("Release has no downloadable assets.")
            import tempfile
            with tempfile.TemporaryDirectory(prefix="frameshot-update-") as d:
                path = _up.download_asset(asset["url"], d)
                if prog.wasCanceled():
                    self.update_status.setText("Update cancelled.")
                    return
                _up.pip_install(path)
        except Exception as e:  # noqa: BLE001
            self.update_status.setText(f"Update failed: {e}")
            return
        finally:
            prog.close()
        self.update_status.setText(f"Updated to {tag} — restarting…")
        from PyQt6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(400, lambda: _up.restart_app())

    def _build_hotkey_section(self, form):
        from . import background as _bg
        self._bg = _bg
        self.hotkey_status = QLabel()
        self.hotkey_status.setWordWrap(True)
        form.addRow("Hotkey status:", self.hotkey_status)
        if _bg.gnome_available():
            self.hotkey_edit = QLineEdit()
            apply_b = QPushButton("Apply")
            clear_b = QPushButton("Clear")
            apply_b.clicked.connect(self._apply_hotkey)
            clear_b.clicked.connect(self._clear_hotkey)
            hrow = QHBoxLayout()
            hrow.addWidget(self.hotkey_edit)
            hrow.addWidget(apply_b)
            hrow.addWidget(clear_b)
            hwrap = QWidget()
            hwrap.setLayout(hrow)
            form.addRow("Hotkey (e.g. <Primary><Shift>f):", hwrap)
            note = QLabel("Wayland hotkeys live in the compositor — "
                          "frameshot writes GNOME's keybinding store directly.")
            note.setWordWrap(True)
            form.addRow(note)
        else:
            hint = _bg.compositor_hint() or (
                "Global hotkeys live in the compositor — bind one to `frameshot`.")
            hint_l = QLabel(hint)
            hint_l.setWordWrap(True)
            form.addRow(hint_l)
            self.hotkey_edit = None
        self._refresh_hotkey()

    def _refresh_hotkey(self):
        try:
            binding, command = self._bg.gnome_binding()
        except Exception:  # noqa: BLE001
            binding, command = None, None
        if binding:
            try:
                clashes = self._bg.find_binding_conflicts(binding)
            except Exception:  # noqa: BLE001
                clashes = []
            txt = f"{binding} → {command or 'frameshot'}"
            if clashes:
                who = ", ".join(n or p for p, n, _c in clashes)
                txt += f"  ⚠ ALSO USED BY: {who} — press will clash"
            self.hotkey_status.setText(txt)
            if self.hotkey_edit is not None and not self.hotkey_edit.hasFocus():
                self.hotkey_edit.setText(binding)
        else:
            self.hotkey_status.setText("none — press Apply to install Ctrl+Shift+F")

    def _apply_hotkey(self):
        from .background import DEFAULT_BINDING, SUGGESTED_BINDING
        binding = (self.hotkey_edit.text().strip() or DEFAULT_BINDING)
        try:
            clashes = self._bg.find_binding_conflicts(binding)
        except Exception:  # noqa: BLE001
            clashes = []
        if clashes:
            who = ", ".join(n or p for p, n, _c in clashes)
            self.hotkey_status.setText(
                f"Blocked: {binding} is already used by {who}. "
                f"Try {SUGGESTED_BINDING}.")
            return
        try:
            self._bg.set_gnome_binding(binding)
            self.hotkey_status.setText(f"{binding} → frameshot (active now)")
        except Exception as e:  # noqa: BLE001
            self.hotkey_status.setText(f"Could not set hotkey: {e}")

    def _clear_hotkey(self):
        try:
            self._bg.clear_gnome_binding()
        except Exception:  # noqa: BLE001
            pass
        self._refresh_hotkey()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Save folder", self.save_dir.text())
        if d:
            self.save_dir.setText(d)

    def apply(self):
        self.settings.save_to_disk = self.save_disk.isChecked()
        self.settings.save_dir = self.save_dir.text()
        self.settings.image_format = self.fmt.currentText()
        self.settings.ocr_engine = self.ocr_engine.currentText()
        self.settings.ocr_lang = self.ocr_lang.text().strip() or "en"
        self.settings.portal_interactive_fallback = self.interactive_fb.isChecked()
        try:
            self._bg.set_autostart(self.autostart_box.isChecked())
        except Exception:  # noqa: BLE001
            pass
        self.settings.save()
        return self.settings


class StageSession:
    """Coordinates one overlay window per monitor.

    Wayland places each fullscreen window on exactly one output, so frameshot
    shows every screen's own pixels on that screen (never a squeezed
    dual-monitor stitch). Selection + annotation live on one overlay at a
    time; starting a snip elsewhere moves the session there. Copy/cancel
    closes every overlay.
    """

    def __init__(self):
        self.overlays: list["FrameshotOverlay"] = []
        self._closing = False

    def add(self, ov: "FrameshotOverlay"):
        ov.session = self
        self.overlays.append(ov)

    def selection_started(self, active: "FrameshotOverlay"):
        for o in self.overlays:
            if o is not active:
                o.drop_selection()

    def finish(self):
        if self._closing:
            return
        self._closing = True
        for o in list(self.overlays):
            o.close()

    def any_visible(self) -> bool:
        return any(o.isVisible() for o in self.overlays)


class FrameshotOverlay(QWidget):
    """Fullscreen select → annotate → copy, all in one window."""

    def __init__(self, pixmap: QPixmap, settings, session: StageSession | None = None,
                 preselect_full: bool = False, parent=None):
        super().__init__(parent)
        self._full = pixmap
        self.session = session
        self.settings = settings
        self.tool = Tool.MOVE
        self.sel = QRect()
        self._press = QPoint()
        self._drag_mode: str | None = None  # new | move | resize-i
        self._resize_idx = -1
        self.shapes: list[Shape] = []
        self.redo_stack: list[Shape] = []
        self._draft: Shape | None = None
        self._sel_text: Shape | None = None  # selected text object
        self._text_drag: dict | None = None  # move/resize/rotate in progress
        self._editing_shape: Shape | None = None  # inline edit target
        self._hover = QPoint()
        self.pen_color = settings.pen_color
        self.pen_width = settings.pen_width
        self.font_size = settings.font_size
        self._ocr_worker = None
        self._preselect_full = preselect_full

        self.setWindowTitle("frameshot")
        # NOTE: no BypassWindowManagerHint — on Wayland it breaks output
        # placement (the window lands on one screen only). Frameless +
        # fullscreen per output is the correct overlay recipe.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint)
        self.setMouseTracking(True)
        # Snip-ready from the first frameshot: the overlay opens for selecting.
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._build_chrome()
        if preselect_full:
            # Interactive-portal shots are already composed: annotate all.
            QTimer.singleShot(0, self._select_all)

    # -- geometry -------------------------------------------------------
    def show_on_screen(self, screen):
        """Fullscreen this overlay on one specific output.

        `self._full` must be that output's crop (in source pixels); it is
        painted 1:1 onto the screen geometry (uniform per-output scale from
        the capture is handled by _to_px for HiDPI).
        """
        self.setGeometry(screen.geometry())
        self._bg = self._full.scaled(
            screen.geometry().size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        # Pin to the output: create the native window first, then bind it.
        self.winId()
        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(screen)
        self.showFullScreen()
        self._layout_chrome()

    def _to_px(self, rect: QRect) -> QRect:
        """Widget coords -> source pixmap pixels (handles scaling)."""
        g = self.geometry()
        if g.width() <= 0 or self._full.width() <= 0:
            return QRect(rect)
        sx = self._full.width() / g.width()
        sy = self._full.height() / g.height()
        return QRect(int(rect.x() * sx), int(rect.y() * sy),
                     int(rect.width() * sx), int(rect.height() * sy))

    # -- chrome (toolbar / ocr popup / text field) ----------------------
    def _tool_btn(self, name: str, tip: str, checkable=True) -> QToolButton:
        b = QToolButton()
        b.setIcon(_icons.icon(name))
        b.setIconSize(QSize(20, 20))
        b.setFixedSize(_icons.icon_size())
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _build_chrome(self):
        self.bar = QFrame(self)
        self.bar.setObjectName("bar")
        self.bar.setStyleSheet(TOOLBAR_QSS)
        layout = QVBoxLayout(self.bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(2)
        self._tool_btns: dict[Tool, QToolButton] = {}
        for tool, name, tip in [
            (Tool.MOVE, "move", "Move / resize selection (V)"),
            (Tool.RECT, "rect", "Rectangle (R)"),
            (Tool.ELLIPSE, "ellipse", "Ellipse (C)"),
            (Tool.ARROW, "arrow", "Arrow (A)"),
            (Tool.LINE, "line", "Line (L)"),
            (Tool.PEN, "pen", "Pen (P)"),
            (Tool.TEXT, "text", "Text (T)"),
            (Tool.BLUR, "blur", "Blur (B)"),
        ]:
            b = self._tool_btn(name, tip)
            b.clicked.connect(lambda _c=False, t=tool: self.set_tool(t))
            row1.addWidget(b)
            self._tool_btns[tool] = b
        self._tool_btns[Tool.MOVE].setChecked(True)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(4)
        self._color_btns: list[QToolButton] = []
        for c in COLORS:
            b = QToolButton()
            b.setFixedSize(QSize(22, 22))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(c)
            b.setStyleSheet(
                f"QToolButton {{ background: {c}; border-radius: 11px;"
                f" border: 2px solid transparent; }}"
                f"QToolButton:checked {{ border: 2px solid white; }}")
            b.clicked.connect(lambda _c=False, col=c: self.set_color(col))
            row2.addWidget(b)
            self._color_btns.append(b)
        self._sync_colors()
        self.width_slider = QSlider(Qt.Orientation.Horizontal)
        self.width_slider.setRange(0, len(WIDTHS) - 1)
        self.width_slider.setFixedWidth(70)
        try:
            self.width_slider.setValue(WIDTHS.index(self.pen_width))
        except ValueError:
            self.width_slider.setValue(1)
        self.width_slider.setToolTip("Stroke width")
        self.width_slider.valueChanged.connect(
            lambda i: self.set_width(WIDTHS[i]))
        row2.addWidget(self.width_slider)
        self.undo_btn = self._tool_btn("undo", "Undo (Ctrl+Z)", checkable=False)
        self.undo_btn.clicked.connect(self.undo)
        row2.addWidget(self.undo_btn)
        self.ocr_btn = self._tool_btn("ocr", "Text from image (OCR)", checkable=True)
        self.ocr_btn.toggled.connect(self._toggle_ocr)
        row2.addWidget(self.ocr_btn)
        save_b = self._tool_btn("save", "Save to file (Ctrl+S)", checkable=False)
        save_b.clicked.connect(self.save_interactive)
        row2.addWidget(save_b)
        gear_b = self._tool_btn("gear", "Settings", checkable=False)
        gear_b.clicked.connect(self.open_settings)
        row2.addWidget(gear_b)
        copy_b = self._tool_btn("check", "Copy to clipboard (Enter)", checkable=False)
        copy_b.setObjectName("primary")
        copy_b.setStyleSheet(TOOLBAR_QSS)
        copy_b.clicked.connect(self.copy_and_close)
        row2.addWidget(copy_b)
        close_b = self._tool_btn("close", "Cancel (Esc)", checkable=False)
        close_b.clicked.connect(self._cancel)
        row2.addWidget(close_b)
        layout.addLayout(row2)
        self.bar.hide()

        # OCR popup: small card floating right above the snip, so the text
        # is read next to the pixels it came from (not docked at a screen edge)
        self.popup = QFrame(self)
        self.popup.setObjectName("card")
        self.popup.setStyleSheet(CARD_QSS)
        self.popup.setFixedSize(400, 248)
        cl = QVBoxLayout(self.popup)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(6)
        title_row = QHBoxLayout()
        title = QLabel("Text in this snip")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        title_row.addWidget(title, stretch=1)
        x_b = QPushButton("✕")
        x_b.setFixedSize(26, 26)
        x_b.setToolTip("Close (Esc)")
        x_b.clicked.connect(lambda: self.ocr_btn.setChecked(False))
        title_row.addWidget(x_b)
        cl.addLayout(title_row)
        mid_row = QHBoxLayout()
        self.ocr_lang = QComboBox()
        self.ocr_lang.setEditable(True)
        self.ocr_lang.addItems(["en", "de", "fr", "es", "ch"])
        self.ocr_lang.setCurrentText(self.settings.ocr_lang)
        self.ocr_lang.setFixedWidth(90)
        rerun_b = QPushButton("Re-run")
        rerun_b.setToolTip("Run OCR again on the current selection")
        rerun_b.clicked.connect(self.run_ocr)
        copy_t = QPushButton("Copy text")
        copy_t.setObjectName("go")
        copy_t.clicked.connect(self.copy_ocr_text)
        mid_row.addWidget(self.ocr_lang)
        mid_row.addWidget(rerun_b)
        mid_row.addWidget(copy_t)
        cl.addLayout(mid_row)
        self.ocr_text = QTextEdit()
        self.ocr_text.setPlaceholderText("Recognized text lands here — editable.")
        self.ocr_text.setMinimumHeight(110)
        cl.addWidget(self.ocr_text, stretch=1)
        self.ocr_status = QLabel("Reading…")
        self.ocr_status.setWordWrap(True)
        self.ocr_status.setStyleSheet("color: rgba(255,255,255,170);")
        cl.addWidget(self.ocr_status)
        self.popup.hide()

        # inline text editor (multiline: Shift+Enter breaks lines,
        # plain Enter places the text AND copies+closes the snip)
        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setStyleSheet(
            "QPlainTextEdit { background: rgba(20,20,24,235); color: white;"
            " border: 2px solid %s; border-radius: 8px; padding: 4px 8px; }" % ACCENT)
        self.text_edit.setPlaceholderText("Type…  (Shift+Enter: new line)")
        self.text_edit.hide()
        self.text_edit.installEventFilter(self)
        self._text_pos = QPoint()

        # hint pill
        self.hint = QLabel(
            "Drag to snip   •   Enter: copy   •   Esc: cancel", self)
        self.hint.setObjectName("dim")
        self.hint.setStyleSheet(
            "QLabel { background: rgba(20,20,24,200); color: white;"
            " border-radius: 10px; padding: 6px 14px; font-size: 13px; }")
        self.hint.adjustSize()

        # pre-selection dock: settings + cancel, always visible until a snip
        # exists — so Settings is discoverable the moment frameshot opens.
        self.predock = QFrame(self)
        self.predock.setObjectName("bar")
        self.predock.setStyleSheet(TOOLBAR_QSS)
        pl = QHBoxLayout(self.predock)
        pl.setContentsMargins(6, 6, 6, 6)
        pl.setSpacing(2)
        pg = self._tool_btn("gear", "Settings — background, hotkey, save, OCR",
                            checkable=False)
        pg.clicked.connect(self.open_settings)
        pl.addWidget(pg)
        px = self._tool_btn("close", "Cancel (Esc)", checkable=False)
        px.clicked.connect(self._cancel)
        pl.addWidget(px)
        self.predock.hide()

    def _layout_chrome(self):
        self.hint.move((self.width() - self.hint.width()) // 2, 18)
        self.hint.show()
        self.predock.adjustSize()
        self.predock.move(self.width() - self.predock.width() - 12,
                          self.height() - self.predock.height() - 12)
        if self.sel.isNull():
            self.predock.show()
        self._place_bar()

    def _claim_selection(self):
        """Starting a fresh snip: clear local canvas, deactivate siblings."""
        self.shapes.clear()
        self.redo_stack.clear()
        self._draft = None
        self._sel_text = None
        self._text_drag = None
        self._editing_shape = None
        self.text_edit.hide()
        self.bar.hide()
        self.hint.hide()
        self.predock.hide()
        if self.session is not None:
            self.session.selection_started(self)

    def drop_selection(self):
        """Silently deactivate (another monitor took over the session)."""
        self.sel = QRect()
        self.shapes.clear()
        self.redo_stack.clear()
        self._draft = None
        self._sel_text = None
        self._text_drag = None
        self._editing_shape = None
        self.text_edit.hide()
        self.bar.hide()
        self.popup.hide()
        self.ocr_btn.setChecked(False)
        self.hint.show()
        self.predock.show()
        self.set_tool(Tool.MOVE)
        self.update()

    def _cancel(self):
        if self.session is not None:
            self.session.finish()
        else:
            self.close()

    def closeEvent(self, event):  # noqa: N802
        self._stop_ocr_worker()
        if self.session is not None:
            self.session.finish()
        super().closeEvent(event)

    def _select_all(self):
        self.sel = self.rect().adjusted(2, 2, -4, -4)
        self.bar.show()
        self.hint.hide()
        self.predock.hide()
        self._place_bar()
        self.update()

    def _place_bar(self):
        if self.sel.isNull():
            self.bar.hide()
            self.predock.show()
            return
        self.predock.hide()
        self.bar.show()
        self.bar.adjustSize()
        bw, bh = self.bar.width(), self.bar.height()
        x = min(max(self.sel.left(), 8), self.width() - bw - 8)
        y = self.sel.bottom() + 10
        if y + bh > self.height() - 8:
            y = max(8, self.sel.top() - bh - 10)
        self.bar.move(x, y)
        self._place_popup()

    def _place_popup(self):
        """Float the OCR popup right above the snip (else below toolbar)."""
        if not self.popup.isVisible() or self.sel.isNull():
            return
        pw, ph = self.popup.width(), self.popup.height()
        x = min(max(self.sel.left(), 8), self.width() - pw - 8)
        y = self.sel.top() - ph - 8
        if y < 8:
            below_bar = self.bar.y() + self.bar.height() + 8 \
                if self.bar.isVisible() else self.sel.bottom() + 10
            y = below_bar
            if y + ph > self.height() - 8:
                y = max(8, (self.height() - ph) // 2)
        self.popup.move(int(x), int(y))

    # -- toolbar slots --------------------------------------------------
    def set_tool(self, t: Tool):
        self.tool = t
        for k, b in self._tool_btns.items():
            b.setChecked(k == t)
        # Crosshair whenever snipping/drawing may start; hover refines it.
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_color(self, c: str):
        self.pen_color = c
        self.settings.pen_color = c
        self._sync_colors()
        # Recolor the selected text live — the choice is visible at once.
        if self._sel_text is not None and self._sel_text in self.shapes:
            self._sel_text.color = c
            self.update()

    def _sync_colors(self):
        for b, c in zip(self._color_btns, COLORS):
            b.setChecked(c == self.pen_color)

    def set_width(self, w: int):
        self.pen_width = w
        self.settings.pen_width = w

    def undo(self):
        if self.shapes:
            self.redo_stack.append(self.shapes.pop())
            self.update()

    def _toggle_ocr(self, on: bool):
        if not on:
            self._stop_ocr_worker()
        self.popup.setVisible(on)
        self._layout_chrome()
        if on:
            # Opening the popup IS the request: run immediately, no 2nd click.
            self.run_ocr()

    def _stop_ocr_worker(self):
        w = self._ocr_worker
        if w is not None and w.isRunning():
            w.blockSignals(True)
            w.terminate()
            w.wait(3000)
        self._ocr_worker = None

    def _locked(self) -> bool:
        """Canvas input locked while the OCR popup is open.

        Nothing may change under the OCR result (no re-snip, no drawing)
        until the popup is closed with Escape (or its toggle button).
        """
        return self.popup.isVisible()

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            dlg.apply()
            self.pen_width = self.settings.pen_width
            self.ocr_lang.setCurrentText(self.settings.ocr_lang)

    # -- selection + drawing input --------------------------------------
    def _handles(self) -> list[QPoint]:
        r = self.sel
        return [
            r.topLeft(), QPoint((r.left() + r.right()) // 2, r.top()),
            r.topRight(), QPoint(r.right(), (r.top() + r.bottom()) // 2),
            r.bottomRight(), QPoint((r.left() + r.right()) // 2, r.bottom()),
            r.bottomLeft(), QPoint(r.left(), (r.top() + r.bottom()) // 2),
        ]

    def _handle_at(self, pos: QPoint) -> int:
        for i, h in enumerate(self._handles()):
            if (h - pos).manhattanLength() <= 9:
                return i
        return -1

    # -- text objects (select / move / resize / rotate) ------------------
    @staticmethod
    def _text_font(s: Shape) -> QFont:
        f = QFont()
        f.setPointSize(s.font_size)
        f.setBold(True)
        return f

    @classmethod
    def _text_size(cls, s: Shape) -> QSizeF:
        """Content size (no grab padding); p1 is the top-left origin."""
        fm = QFontMetricsF(cls._text_font(s))
        br = fm.boundingRect(
            QRectF(0, 0, 1e6, 1e6),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            s.text or " ")
        return QSizeF(max(20.0, br.width()), max(fm.height(), br.height()))

    @classmethod
    def _text_local_rect(cls, s: Shape) -> QRectF:
        """Grab rect in top-left-origin coords (padded for easy grabbing)."""
        z = cls._text_size(s)
        pad = 8.0
        return QRectF(-pad, -pad, z.width() + 2 * pad, z.height() + 2 * pad)

    @staticmethod
    def _text_transform(s: Shape, off: QPoint) -> QTransform:
        t = QTransform()
        t.translate(s.p1.x() + off.x(), s.p1.y() + off.y())
        t.rotate(s.angle)
        return t

    @classmethod
    def _text_corners(cls, s: Shape, off: QPoint) -> list[QPointF]:
        r = cls._text_local_rect(s)
        t = cls._text_transform(s, off)
        return [t.map(QPointF(r.left(), r.top())),
                t.map(QPointF(r.right(), r.top())),
                t.map(QPointF(r.right(), r.bottom())),
                t.map(QPointF(r.left(), r.bottom()))]

    @classmethod
    def _text_center(cls, s: Shape, off: QPoint) -> QPointF:
        return cls._text_transform(s, off).map(
            cls._text_local_rect(s).center())

    @classmethod
    def _text_rot_handle(cls, s: Shape, off: QPoint) -> QPointF:
        r = cls._text_local_rect(s)
        top = QPointF(r.center().x(), r.top())
        return cls._text_transform(s, off).map(top + QPointF(0, -30))

    @classmethod
    def _text_hit(cls, s: Shape, pos: QPoint, off: QPoint) -> str | None:
        """'rotate' | 'resize' | 'move' | None for a widget-space point."""
        for c in cls._text_corners(s, off):
            if QPointF(c - QPointF(pos)).manhattanLength() <= 11:
                return "resize"
        if QPointF(cls._text_rot_handle(s, off) - QPointF(pos)
                   ).manhattanLength() <= 12:
            return "rotate"
        inv, ok = cls._text_transform(s, off).inverted()
        if ok and cls._text_local_rect(s).contains(inv.map(QPointF(pos))):
            return "move"
        return None

    def _text_hit_test(self, pos: QPoint) -> tuple[Shape, str] | None:
        for s in reversed(self.shapes):
            if s.kind != Tool.TEXT:
                continue
            part = self._text_hit(s, pos, QPoint(0, 0))
            if part is not None:
                return s, part
        return None

    def _draw_text_chrome(self, p: QPainter, s: Shape):
        corners = self._text_corners(s, QPoint(0, 0))
        poly = QPolygonF(corners)
        p.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(poly)
        for c in corners:
            p.setPen(QPen(QColor(ACCENT), 1.5))
            p.setBrush(QColor("#ffffff"))
            p.drawRect(QRectF(c.x() - 4, c.y() - 4, 8, 8))
        h = self._text_rot_handle(s, QPoint(0, 0))
        top = self._text_transform(s, QPoint(0, 0)).map(
            self._text_local_rect(s).center() +
            QPointF(0, -self._text_local_rect(s).height() / 2))
        p.setPen(QPen(QColor(ACCENT), 1.5))
        p.drawLine(top, h)
        p.setBrush(QColor(ACCENT))
        p.drawEllipse(h, 6, 6)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._locked():
            return  # OCR popup open: canvas frozen until it closes
        pos = event.pos()
        if self.tool == Tool.MOVE or self.sel.isNull():
            if self.tool == Tool.MOVE and not self.sel.isNull():
                hit = self._text_hit_test(pos)
                if hit is not None:
                    s, part = hit
                    self._sel_text = s
                    c = self._text_center(s, QPoint(0, 0))
                    self._text_drag = {
                        "part": part, "last": QPoint(pos),
                        "cx": c.x(), "cy": c.y(),
                        "d0": max(1.0, math.hypot(c.x() - pos.x(),
                                                  c.y() - pos.y())),
                        "font0": s.font_size,
                    }
                    self.update()
                    return
                self._sel_text = None
            idx = -1 if self.sel.isNull() else self._handle_at(pos)
            if idx >= 0:
                self._drag_mode, self._resize_idx = "resize", idx
            elif not self.sel.isNull() and self.sel.contains(pos):
                self._drag_mode, self._press = "move", pos
            else:
                self._drag_mode, self._press = "new", pos
                self.sel = QRect(pos, pos)
                self._claim_selection()
        else:
            # annotation tool: outside selection restarts the snip
            if not self.sel.isNull() and not self.sel.contains(pos):
                self._drag_mode, self._press = "new", pos
                self.sel = QRect(pos, pos)
                self._claim_selection()
                return
            if self.tool == Tool.TEXT:
                self._begin_text(pos)  # edits hit text, else starts new
                return
            if self.tool == Tool.PEN:
                self._draft = Shape(kind=Tool.PEN, points=[pos],
                                    color=self.pen_color, width=self.pen_width)
            else:
                self._draft = Shape(kind=self.tool, p1=pos, p2=pos,
                                    color=self.pen_color, width=self.pen_width,
                                    font_size=self.font_size)
            self._drag_mode = "draw"
        self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.pos()
        self._hover = pos
        if self._text_drag is not None:
            self._move_text_drag(pos)
            self.update()
            return
        if self._drag_mode == "new":
            self.sel = QRect(self._press, pos).normalized()
        elif self._drag_mode == "move":
            delta = pos - self._press
            self.sel.translate(delta)
            self._press = pos
        elif self._drag_mode == "resize":
            self._apply_resize(pos)
        elif self._drag_mode == "draw" and self._draft is not None:
            if self._draft.kind == Tool.PEN:
                self._draft.points.append(pos)
            else:
                self._draft.p2 = pos
        else:
            self._update_hover_cursor(pos)
            self.update()
            return
        self._place_bar()
        self.update()

    def _move_text_drag(self, pos: QPoint):
        d = self._text_drag
        s = self._sel_text
        if d is None or s is None or s not in self.shapes:
            self._text_drag = None
            return
        if d["part"] == "move":
            s.p1 = s.p1 + (pos - d["last"])
            d["last"] = QPoint(pos)
        elif d["part"] == "resize":
            dist = math.hypot(pos.x() - d["cx"], pos.y() - d["cy"])
            f = dist / d["d0"]
            s.font_size = max(8, min(120, round(d["font0"] * f)))
        elif d["part"] == "rotate":
            ang = math.degrees(math.atan2(pos.y() - d["cy"],
                                          pos.x() - d["cx"])) + 90.0
            s.angle = ((ang + 180.0) % 360.0) - 180.0

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            if not self._locked():
                self._cancel()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._text_drag is not None:
            self._text_drag = None  # keep the text selected
            self.update()
            return
        mode, self._drag_mode = self._drag_mode, None
        if mode == "new":
            self.sel = QRect(self._press, event.pos()).normalized()
            if self.sel.width() < 5 or self.sel.height() < 5:
                self.sel = QRect()
                self.hint.show()
            else:
                self._place_bar()
        elif mode == "draw" and self._draft is not None:
            d = self._draft
            self._draft = None
            if d.kind == Tool.PEN and len(d.points) < 2:
                pass
            elif d.kind != Tool.PEN and QRect(d.p1, d.p2).normalized().width() < 3 \
                    and QRect(d.p1, d.p2).normalized().height() < 3 \
                    and d.kind in (Tool.RECT, Tool.ELLIPSE, Tool.BLUR):
                pass
            else:
                self.shapes.append(d)
                self.redo_stack.clear()
        if mode in ("new", "move", "resize") and self.popup.isVisible() \
                and not self.sel.isNull():
            self.run_ocr()  # selection moved under an open popup: refresh
        self._place_bar()
        self.update()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if not self.sel.isNull() and self.sel.contains(event.pos()):
            self.copy_and_close()

    def _apply_resize(self, pos: QPoint):
        r, i = self.sel, self._resize_idx
        if i == 0:
            r.setTopLeft(pos)
        elif i == 1:
            r.setTop(pos.y())
        elif i == 2:
            r.setTopRight(pos)
        elif i == 3:
            r.setRight(pos.x())
        elif i == 4:
            r.setBottomRight(pos)
        elif i == 5:
            r.setBottom(pos.y())
        elif i == 6:
            r.setBottomLeft(pos)
        elif i == 7:
            r.setLeft(pos.x())
        self.sel = r.normalized()

    def _update_hover_cursor(self, pos: QPoint):
        if self.sel.isNull() or self.tool != Tool.MOVE:
            return
        idx = self._handle_at(pos)
        cursors = [Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeVerCursor,
                   Qt.CursorShape.SizeBDiagCursor, Qt.CursorShape.SizeHorCursor,
                   Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeVerCursor,
                   Qt.CursorShape.SizeBDiagCursor, Qt.CursorShape.SizeHorCursor]
        if idx >= 0:
            self.setCursor(cursors[idx])
        elif self.sel.contains(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    # -- inline text ----------------------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802, ANN001, ANN202
        if obj is self.text_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False  # Shift+Enter: newline inside the text
                self._commit_text()
                self.copy_and_close()  # Enter: place text, copy, done
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.text_edit.hide()
                self._editing_shape = None
                self.setFocus()
                return True
        return super().eventFilter(obj, event)

    def _begin_text(self, pos: QPoint):
        if self.text_edit.isVisible():
            self._commit_text()  # click-away places pending text first,
            # so texts accumulate instead of exactly one ever existing
        shape = None
        hit = self._text_hit_test(pos)
        if hit is not None:
            shape, _part = hit  # click on text = edit it in place
        self._editing_shape = shape
        self._sel_text = shape
        self._text_pos = shape.p1 if shape is not None else QPoint(pos)
        fs = shape.font_size if shape is not None else self.font_size
        self.text_edit.setFont(QFont("", fs, QFont.Weight.Bold))
        self.text_edit.setPlainText(shape.text if shape is not None else "")
        self.text_edit.setGeometry(self._text_pos.x(),
                                   self._text_pos.y() - fs - 22, 280, 64)
        self.text_edit.show()
        self.text_edit.setFocus()

    def _commit_text(self):
        t = self.text_edit.toPlainText().strip()
        self.text_edit.hide()
        self.setFocus()
        if self._editing_shape is not None:
            if t:
                self._editing_shape.text = t
            else:
                try:
                    self.shapes.remove(self._editing_shape)
                except ValueError:
                    pass
                if self._sel_text is self._editing_shape:
                    self._sel_text = None
            self._editing_shape = None
        elif t:
            self.shapes.append(Shape(kind=Tool.TEXT, p1=QPoint(self._text_pos),
                                     text=t, color=self.pen_color,
                                     font_size=self.font_size,
                                     width=self.pen_width))
            self.redo_stack.clear()
        self.update()

    # -- paint ----------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802, ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = getattr(self, "_bg", self._full)
        p.drawPixmap(self.rect(), bg)
        if self.sel.isNull() or self.sel.width() < 2:
            p.fillRect(self.rect(), QColor(0, 0, 0, 70))
            self._draw_loupe(p, bg)
            p.end()
            return
        # dim everything outside the selection
        p.setClipRegion(QRegion(self.rect()).subtracted(QRegion(self.sel)))
        p.fillRect(self.rect(), QColor(0, 0, 0, 150))
        p.setClipping(False)
        # annotations, clipped to the selection
        p.save()
        p.setClipRect(self.sel)
        self._paint_shapes(p, self.shapes, QPoint(0, 0))
        if self._draft is not None:
            self._paint_shapes(p, [self._draft], QPoint(0, 0))
        if self._sel_text is not None and self._sel_text in self.shapes:
            self._draw_text_chrome(p, self._sel_text)
        p.restore()
        # selection chrome
        p.setPen(QPen(QColor(ACCENT), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.sel.adjusted(1, 1, -1, -1))
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor(ACCENT), 1.5))
        for h in self._handles():
            p.drawRect(h.x() - 4, h.y() - 4, 8, 8)
        label = f"{self.sel.width()} × {self.sel.height()}"
        fm = p.fontMetrics()
        bw = fm.horizontalAdvance(label) + 16
        bh = fm.height() + 8
        lx = min(max(self.sel.left(), 8), self.width() - bw - 8)
        ly = self.sel.bottom() + 8
        if ly + bh > self.height() - 8:
            ly = max(8, self.sel.top() - bh - 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 24, 220))
        p.drawRoundedRect(int(lx), int(ly), int(bw), int(bh), 7, 7)
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(int(lx), int(ly), int(bw), int(bh),
                   Qt.AlignmentFlag.AlignCenter, label)
        p.end()

    def _paint_shapes(self, p: QPainter, shapes: list[Shape], off: QPoint):
        for s in shapes:
            a, b = s.p1 + off, s.p2 + off
            if s.kind == Tool.BLUR:
                base = getattr(self, "_blur_base", None)
                self._paint_blur(p, QRect(a, b).normalized(), base)
                continue
            pen = QPen(QColor(s.color), s.width, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if s.kind == Tool.RECT:
                p.drawRect(QRect(a, b))
            elif s.kind == Tool.ELLIPSE:
                p.drawEllipse(QRect(a, b))
            elif s.kind == Tool.LINE:
                p.drawLine(a, b)
            elif s.kind == Tool.ARROW:
                self._draw_arrow(p, a, b, s.width)
            elif s.kind == Tool.PEN:
                pts = [pt + off for pt in s.points]
                for u, v in zip(pts[:-1], pts[1:]):
                    p.drawLine(u, v)
            elif s.kind == Tool.TEXT:
                p.save()
                p.translate(a)
                p.rotate(s.angle)
                p.setFont(self._text_font(s))
                flags = (Qt.AlignmentFlag.AlignLeft |
                         Qt.AlignmentFlag.AlignTop)
                br = QRectF(QPointF(0, 0), self._text_size(s))
                # thin dark outline so color stays readable on any pixels
                p.setPen(QPen(QColor("#000000"), 2))
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    p.drawText(br.translated(dx, dy), flags, s.text)
                p.setPen(QPen(QColor(s.color)))
                p.drawText(br, flags, s.text)
                p.restore()

    def _draw_arrow(self, p: QPainter, a: QPoint, b: QPoint, w: int):
        p.drawLine(a, b)
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        head = max(12, w * 4)
        for spread in (math.pi / 6, -math.pi / 6):
            an = ang + math.pi + spread
            p.drawLine(b, QPoint(int(b.x() + head * math.cos(an)),
                                 int(b.y() + head * math.sin(an))))

    def _paint_blur(self, p: QPainter, rect: QRect, base):
        src = base if base is not None else self._bg
        rect = rect.intersected(QRect(QPoint(0, 0), src.size()))
        if rect.width() < 2 or rect.height() < 2:
            return
        k = max(2, self.settings.blur_strength)
        crop = src.copy(rect)
        tiny = crop.scaled(max(1, rect.width() // k), max(1, rect.height() // k),
                           Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.FastTransformation)
        pix = tiny.scaled(rect.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.FastTransformation)
        p.drawPixmap(rect.topLeft(), pix)

    def _draw_loupe(self, p: QPainter, bg: QPixmap):
        pos = self._hover if not self._hover.isNull() else self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(pos):
            return
        size, zoom = 110, 4
        src = QRect(pos.x() - size // (2 * zoom), pos.y() - size // (2 * zoom),
                    size // zoom, size // zoom).intersected(bg.rect())
        if src.width() < 4:
            return
        crop = bg.copy(src).scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.FastTransformation)
        x = min(max(pos.x() + 18, 4), self.width() - size - 4)
        y = min(max(pos.y() + 18, 4), self.height() - size - 4)
        p.drawPixmap(x, y, crop)
        p.setPen(QPen(QColor("#ffffff"), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(x, y, size, size)
        p.setPen(QPen(QColor(ACCENT), 1))
        p.drawLine(x + size // 2, y, x + size // 2, y + size)
        p.drawLine(x, y + size // 2, x + size, y + size // 2)

    # -- export / actions -----------------------------------------------
    def _render_export(self) -> QPixmap:
        mapped = self._to_px(self.sel).intersected(self._full.rect())
        crop = self._full.copy(mapped)
        out = QPixmap(crop.size())
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, crop)
        off = QPoint(-self.sel.left(), -self.sel.top())
        # blur shapes need the crop as their source
        self._blur_base = crop
        try:
            self._paint_shapes(p, self.shapes, off)
        finally:
            self._blur_base = None
        p.end()
        return out

    def export_png_bytes(self, fmt: str = "PNG", quality: int = 90) -> bytes:
        from PyQt6.QtGui import QImage
        img: QImage = self._render_export().toImage()
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "JPG" if fmt.lower() in ("jpg", "jpeg") else "PNG", quality)
        return bytes(buf.data())

    def copy_and_close(self):
        if self.sel.isNull():
            self._cancel()
            return
        from .clipboard import copy_qimage_to_clipboard, persist_image_via_wlcopy
        final = self._render_export()
        copy_qimage_to_clipboard(final.toImage())
        try:
            persist_image_via_wlcopy(
                self.export_png_bytes(self.settings.image_format,
                                      self.settings.jpg_quality))
        except Exception:  # noqa: BLE001
            pass
        if self.settings.save_to_disk:
            try:
                self._write_disk(self.export_png_bytes(
                    self.settings.image_format, self.settings.jpg_quality))
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "frameshot",
                                    f"Clipboard ok, but disk save failed:\n{e}")
        if self.session is not None:
            self.session.finish()
        else:
            self.close()

    def save_interactive(self):
        if self.sel.isNull():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save screenshot",
            str(Path(self.settings.save_dir) / self._default_filename()),
            "Images (*.png *.jpg)")
        if path:
            data = self.export_png_bytes(
                "jpg" if path.lower().endswith((".jpg", ".jpeg")) else "png",
                self.settings.jpg_quality)
            Path(path).write_bytes(data)

    def _default_filename(self) -> str:
        try:
            return datetime.datetime.now().strftime(self.settings.filename_template)
        except Exception:  # noqa: BLE001
            return "frameshot-shot.png"

    def _write_disk(self, data: bytes) -> Path:
        d = Path(self.settings.save_dir)
        d.mkdir(parents=True, exist_ok=True)
        p = d / self._default_filename()
        p.write_bytes(data)
        return p

    # -- OCR popup ------------------------------------------------------
    def run_ocr(self):
        from .ocr import OCRWorker, resolve_engine
        if self.sel.isNull():
            self.ocr_status.setText("Select an area first.")
            return
        engine = resolve_engine(self.settings.ocr_engine)
        lang = self.ocr_lang.currentText().strip() or "en"
        if engine is None:
            self.ocr_status.setText(
                "No OCR backend. Install tesseract "
                "(`sudo apt install tesseract-ocr`) or paddleocr.")
            return
        self.ocr_status.setText(f"Running {engine} OCR…")
        self._stop_ocr_worker()
        mapped = self._to_px(self.sel).intersected(self._full.rect())
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        self._full.copy(mapped).toImage().save(buf, "PNG")
        self._ocr_worker = OCRWorker(bytes(buf.data()), engine, lang, self)
        self._ocr_worker.finished.connect(self._ocr_done)
        self._ocr_worker.failed.connect(self._ocr_failed)
        self._ocr_worker.start()

    def _ocr_done(self, text: str):
        self.ocr_text.setPlainText(text or "(no text recognized)")
        self.ocr_status.setText("Done — edit above, then Copy text.")

    def _ocr_failed(self, err: str):
        self.ocr_status.setText(f"OCR failed: {err}")

    def copy_ocr_text(self):
        from .clipboard import copy_text_to_clipboard
        copy_text_to_clipboard(self.ocr_text.toPlainText())
        self.ocr_status.setText("Text copied to clipboard.")

    # -- keys -----------------------------------------------------------
    def keyPressEvent(self, event):  # noqa: N802
        if self.text_edit.isVisible() or self.ocr_text.hasFocus():
            if event.key() == Qt.Key.Key_Escape:
                if self.text_edit.isVisible():
                    self.text_edit.hide()
                elif self.popup.isVisible():
                    self.ocr_btn.setChecked(False)
                self.setFocus()
                return
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Escape and self.popup.isVisible():
            # OCR popup closes first; only the next Esc cancels the overlay.
            self.ocr_btn.setChecked(False)
            return
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        k = event.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or \
                (ctrl and k == Qt.Key.Key_C):
            self.copy_and_close()  # Enter or Ctrl+C: copy snip + exit
        elif k == Qt.Key.Key_Escape:
            self._cancel()
        elif ctrl and k == Qt.Key.Key_S:
            self.save_interactive()
        elif ctrl and k == Qt.Key.Key_Z:
            self.undo()
        elif not ctrl and k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) \
                and self._sel_text is not None:
            try:
                self.shapes.remove(self._sel_text)
            except ValueError:
                pass
            self._sel_text = None
            self.update()
        elif not ctrl and k == Qt.Key.Key_V:
            self.set_tool(Tool.MOVE)
        elif not ctrl and k == Qt.Key.Key_R:
            self.set_tool(Tool.RECT)
        elif not ctrl and k == Qt.Key.Key_C:
            self.set_tool(Tool.ELLIPSE)
        elif not ctrl and k == Qt.Key.Key_A:
            self.set_tool(Tool.ARROW)
        elif not ctrl and k == Qt.Key.Key_L:
            self.set_tool(Tool.LINE)
        elif not ctrl and k == Qt.Key.Key_P:
            self.set_tool(Tool.PEN)
        elif not ctrl and k == Qt.Key.Key_T:
            self.set_tool(Tool.TEXT)
        elif not ctrl and k == Qt.Key.Key_B:
            self.set_tool(Tool.BLUR)
        else:
            super().keyPressEvent(event)
