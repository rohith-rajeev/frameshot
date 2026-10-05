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


def _head_on_circle(p: QPainter, cx: float, cy: float, r: float,
                      end_deg: float, ccw: bool):
    """Arrowhead at an arc endpoint, tangent to the circle.

    Qt coords (y grows down); Qt arc angles run counter-clockwise from
    3 o'clock, i.e. endpoint = (cx + r*cos, cy - r*sin). `ccw` picks which
    side the head trails on.
    """
    a = math.radians(end_deg)
    ex = cx + r * math.cos(a)
    ey = cy - r * math.sin(a)
    back = end_deg - 25.0 if ccw else end_deg + 25.0
    b = math.radians(back)
    bx = cx + r * math.cos(b)
    by = cy - r * math.sin(b)
    _arrow(p, QPoint(int(bx), int(by)), QPoint(int(ex), int(ey)))


def icon(name: str, size: int = 22) -> QIcon:
    m = size * 0.22
    x0, y0, x1, y1 = m, m, size - m, size - m
    px, p = _base(size)
    cx, cy = size / 2, size / 2

    if name == "move":
        # Four-way move arrows with an OPEN center (a plain "+" reads as "add").
        gap = size * 0.10
        tip = size / 2 - m + 1
        head = size * 0.17
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            p.drawLine(QPoint(int(cx + dx * gap), int(cy + dy * gap)),
                       QPoint(int(cx + dx * (tip - head * 0.55)),
                              int(cy + dy * (tip - head * 0.55))))
            t = (int(cx + dx * tip), int(cy + dy * tip))
            px_, py_ = -dy, dx  # perpendicular for the head wings
            for sgn in (-1, 1):
                p.drawLine(QPoint(*t),
                           QPoint(int(t[0] - dx * head + px_ * sgn * head * 0.55),
                                  int(t[1] - dy * head + py_ * sgn * head * 0.55)))
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
        # Bold counter-clockwise "revert" arrow (universal undo glyph).
        r = size * 0.30
        start, span = 35.0, 280.0
        p.drawArc(int(cx - r), int(cy - r), int(2 * r), int(2 * r),
                  int(start * 16), int(span * 16))
        _head_on_circle(p, cx, cy, r, start + span, ccw=True)
    elif name == "redo":
        # Clockwise twin of undo.
        r = size * 0.30
        start, span = 145.0, -280.0
        p.drawArc(int(cx - r), int(cy - r), int(2 * r), int(2 * r),
                  int(start * 16), int(span * 16))
        _head_on_circle(p, cx, cy, r, start + span, ccw=False)
    elif name == "ocr":
        # Document with text lines + magnifier: "read text from image".
        dw = int((x1 - x0) * 0.60)
        p.drawRect(int(x0), int(y0), dw, int(y1 - y0))
        for i in range(2):
            yy = int(y0 + 4 + i * (y1 - y0 - 6) / 2.4)
            p.drawLine(int(x0 + 3), yy, int(x0 + dw - 3), yy)
        mr = size * 0.21
        mcx, mcy = x1 - mr - 1, y1 - mr - 1
        p.drawEllipse(int(mcx - mr), int(mcy - mr), int(2 * mr), int(2 * mr))
        p.drawLine(int(mcx + mr * 0.70), int(mcy + mr * 0.70),
                   int(x1 - 1), int(y1 - 1))
    elif name == "copy":
        p.drawRect(int(x0 + 3), int(y0 + 3), int(x1 - x0 - 3), int(y1 - y0 - 3))
        p.drawLine(int(x0), int(y0 + 4), int(x0), int(y1))
        p.drawLine(int(x0), int(y1), int(x0 + 7), int(y1))
    elif name == "save":
        # Floppy disk: body + top shutter with notch + bottom label.
        p.drawRect(int(x0 + 1), int(y0 + 2), int(x1 - x0 - 2), int(y1 - y0 - 3))
        sw = (x1 - x0) * 0.44
        sh = (y1 - y0) * 0.36
        p.drawRect(int(cx - sw / 2), int(y0 + 2), int(sw), int(sh))
        p.drawLine(int(cx), int(y0 + 3), int(cx), int(y0 + 2 + sh))
        lh = (y1 - y0) * 0.30
        p.drawRect(int(x0 + 4), int(y1 - 1 - lh), int(x1 - x0 - 8), int(lh))
    elif name == "close":
        p.drawLine(int(x0 + 2), int(y0 + 2), int(x1 - 2), int(y1 - 2))
        p.drawLine(int(x1 - 2), int(y0 + 2), int(x0 + 2), int(y1 - 2))
    elif name == "check":
        p.drawLine(int(x0 + 1), int(cy), int(cx - 1), int(y1 - 2))
        p.drawLine(int(cx - 1), int(y1 - 2), int(x1 - 1), int(y0 + 3))
    elif name == "gear":
        # Toothed cog (the old circle+spokes read as a sun): 8 chunky teeth,
        # an outer ring tying them together, and a hub hole.
        p.save()
        p.setPen(QPen(QColor("#ffffff"), max(2.0, size * 0.11),
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for a in range(0, 360, 45):
            r = math.radians(a)
            p.drawLine(QPoint(int(cx + size * 0.30 * math.cos(r)),
                              int(cy + size * 0.30 * math.sin(r))),
                       QPoint(int(cx + size * 0.43 * math.cos(r)),
                              int(cy + size * 0.43 * math.sin(r))))
        p.restore()
        rr = size * 0.26
        p.drawEllipse(int(cx - rr), int(cy - rr), int(2 * rr), int(2 * rr))
        hr = size * 0.10
        p.drawEllipse(int(cx - hr), int(cy - hr), int(2 * hr), int(2 * hr))
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
