"""Minimal vector icons for frameshot's floating toolbar.

Drawn at runtime with QPainter (white strokes on transparent), so the UI
stays crisp at any scale with zero asset files.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt, QSize, QPoint
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QIcon, QFont


def _base(size: int) -> tuple[QPixmap, QPainter]:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#ffffff"), max(1.6, size / 12),
               Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    return px, p


def _arrow(p: QPainter, a: QPoint, b: QPoint):
    p.drawLine(a, b)
    ang = math.atan2(b.y() - a.y(), b.x() - a.x())
    head = 5.5
    for spread in (math.pi / 6, -math.pi / 6):
        an = ang + math.pi + spread
        p.drawLine(b, QPoint(int(b.x() + head * math.cos(an)),
                             int(b.y() + head * math.sin(an))))


def icon(name: str, size: int = 22) -> QIcon:
    m = size * 0.22
    x0, y0, x1, y1 = m, m, size - m, size - m
    px, p = _base(size)
    cx, cy = size / 2, size / 2

    if name == "move":
        p.drawLine(int(cx), int(y0), int(cx), int(y1))
        p.drawLine(int(x0), int(cy), int(x1), int(cy))
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            tip = QPoint(int(cx + dx * (size / 2 - m + 1)),
                         int(cy + dy * (size / 2 - m + 1)))
            base = QPoint(int(cx + dx * (size / 2 - m - 3)),
                          int(cy + dy * (size / 2 - m - 3)))
            p.drawLine(base, tip)
    elif name == "rect":
        p.drawRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
    elif name == "ellipse":
        p.drawEllipse(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
    elif name == "arrow":
        _arrow(p, QPoint(int(x0 + 1), int(y1 - 1)), QPoint(int(x1 - 1), int(y0 + 1)))
    elif name == "line":
        p.drawLine(int(x0 + 1), int(y1 - 1), int(x1 - 1), int(y0 + 1))
    elif name == "pen":
        import math as _m
        pts = [QPoint(int(x0 + i * (x1 - x0) / 12),
                      int(cy + _m.sin(i / 1.8) * (y1 - y0) / 3.2))
               for i in range(13)]
        for a, b in zip(pts[:-1], pts[1:]):
            p.drawLine(a, b)
    elif name == "text":
        f = QFont()
        f.setBold(True)
        f.setPixelSize(int(size * 0.62))
        p.setFont(f)
        p.drawText(p.viewport(), Qt.AlignmentFlag.AlignCenter, "T")
    elif name == "blur":
        for i, yy in enumerate([y0 + 2, cy - 1, cy + 3]):
            p.drawLine(int(x0 + i * 2), int(yy), int(x1 - i), int(yy))
        p.setPen(QPen(QColor("#ffffff"), 1.2, Qt.PenStyle.DotLine))
        p.drawRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
    elif name == "undo":
        p.drawArc(int(x0), int(y0 + 1), int(x1 - x0 - 4), int(y1 - y0 - 3), 90 * 16, 180 * 16)
        tip = QPoint(int(x0), int(cy + 1))
        p.drawLine(QPoint(int(x0 + 6), int(cy - 3)), tip)
        p.drawLine(QPoint(int(x0 + 6), int(cy + 5)), tip)
    elif name == "redo":
        p.drawArc(int(x0 + 4), int(y0 + 1), int(x1 - x0 - 4), int(y1 - y0 - 3), 270 * 16, 180 * 16)
        tip = QPoint(int(x1), int(cy + 1))
        p.drawLine(QPoint(int(x1 - 6), int(cy - 3)), tip)
        p.drawLine(QPoint(int(x1 - 6), int(cy + 5)), tip)
    elif name == "ocr":
        p.drawRect(int(x0 + 1), int(y0), int(x1 - x0 - 8), int(y1 - y0))
        for i in range(3):
            yy = int(y0 + 4 + i * (y1 - y0 - 6) / 2)
            p.drawLine(int(x0 + 4), yy, int(x1 - 7), yy)
        _arrow(p, QPoint(int(x1 - 3), int(y1)), QPoint(int(x1 - 1), int(y0 + 2)))
    elif name == "copy":
        p.drawRect(int(x0 + 3), int(y0 + 3), int(x1 - x0 - 3), int(y1 - y0 - 3))
        p.drawLine(int(x0), int(y0 + 4), int(x0), int(y1))
        p.drawLine(int(x0), int(y1), int(x0 + 7), int(y1))
    elif name == "save":
        p.drawRect(int(x0 + 1), int(y0 + 1), int(x1 - x0 - 2), int(y1 - y0 - 2))
        p.drawLine(int(x0 + 1), int(y0 + 7), int(x1 - 1), int(y0 + 7))
        p.drawRect(int(cx - 3), int(y1 - 8), 7, 8)
    elif name == "close":
        p.drawLine(int(x0 + 2), int(y0 + 2), int(x1 - 2), int(y1 - 2))
        p.drawLine(int(x1 - 2), int(y0 + 2), int(x0 + 2), int(y1 - 2))
    elif name == "check":
        p.drawLine(int(x0 + 1), int(cy), int(cx - 1), int(y1 - 2))
        p.drawLine(int(cx - 1), int(y1 - 2), int(x1 - 1), int(y0 + 3))
    elif name == "gear":
        p.drawEllipse(int(cx - 5), int(cy - 5), 10, 10)
        for a in range(0, 360, 45):
            r = math.radians(a)
            p.drawLine(QPoint(int(cx + 7 * math.cos(r)), int(cy + 7 * math.sin(r))),
                       QPoint(int(cx + 10 * math.cos(r)), int(cy + 10 * math.sin(r))))
    p.end()
    return QIcon(px)


def dot(color: str, size: int = 18, checked: bool = False) -> QIcon:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(QPen(QColor("#ffffff"), 2 if checked else 1))
    p.drawEllipse(2, 2, size - 4, size - 4)
    p.end()
    return QIcon(px)


def icon_size() -> QSize:
    return QSize(34, 34)
