#!/usr/bin/env python3
"""Render frameshot's app icon PNGs from the frameshot.svg design (Qt, offscreen).

Usage: QT_QPA_PLATFORM=offscreen python3 assets/make-icon.py
Writes assets/frameshot-256.png and assets/frameshot-48.png.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import (
    QPixmap, QPainter, QPen, QColor, QLinearGradient,
)
from PyQt6.QtWidgets import QApplication

ACCENT = "#0a84ff"


def render(size: int) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    k = size / 256.0

    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0, QColor("#33373e"))
    grad.setColorAt(1, QColor("#16181c"))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(int(8 * k), int(8 * k), int(240 * k), int(240 * k),
                      int(56 * k), int(56 * k))

    def bracket(pts, color):
        pen = QPen(QColor(color), 14 * k, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        q = [QPoint(int(x * k), int(y * k)) for x, y in pts]
        p.drawPolyline(*q)

    w = "#ffffff"
    bracket([(52, 116), (52, 52), (116, 52)], w)
    bracket([(140, 52), (204, 52), (204, 116)], w)
    bracket([(52, 140), (52, 204), (116, 204)], w)
    bracket([(140, 204), (204, 204), (204, 140)], ACCENT)
    p.end()
    return px


def main() -> None:
    app = QApplication([])
    here = os.path.dirname(os.path.abspath(__file__))
    for size in (256, 48):
        out = os.path.join(here, f"frameshot-{size}.png")
        if not render(size).save(out, "PNG"):
            raise SystemExit(f"failed to write {out}")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
