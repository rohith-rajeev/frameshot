"""OCR backends. Pointer #4: PaddleOCR preferred, Tesseract fallback.

Design for lightness (pointer: no overhead):
- No OCR library is imported at startup. Imports happen lazily inside the
  worker thread on first "Run OCR" click.
- Engine "auto": use PaddleOCR if installed, else `tesseract` binary.
- Result is shown in the right pane (no new windows) with edit + copy.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal


def available_engines() -> list[str]:
    engines = []
    try:
        import paddleocr  # noqa: F401
        engines.append("paddle")
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("tesseract"):
        engines.append("tesseract")
    return engines


def resolve_engine(preference: str) -> str | None:
    """Map config preference to a concrete engine name or None."""
    if preference == "off":
        return None
    if preference in ("paddle", "tesseract"):
        return preference
    # auto
    av = available_engines()
    if "paddle" in av:
        return "paddle"
    if "tesseract" in av:
        return "tesseract"
    return None


def ocr_png_bytes(png_bytes: bytes, engine: str, lang: str = "en") -> str:
    if engine == "paddle":
        return _ocr_paddle(png_bytes, lang)
    if engine == "tesseract":
        return _ocr_tesseract(png_bytes, lang)
    raise RuntimeError(f"Unknown OCR engine: {engine}")


def _ocr_tesseract(png_bytes: bytes, lang: str = "en") -> str:
    tess_lang = "eng" if lang.lower().startswith("en") else lang
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(png_bytes)
        tmp = tf.name
    try:
        p = subprocess.run(
            ["tesseract", tmp, "stdout", "--oem", "1", "--psm", "6",
             "-l", tess_lang],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
        )
        if p.returncode != 0:
            raise RuntimeError(f"tesseract failed: {p.stderr.decode()[:300]}")
        return p.stdout.decode("utf-8", errors="replace").strip()
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def _ocr_paddle(png_bytes: bytes, lang: str = "en") -> str:
    # Lazy, heavy imports stay out of the startup path.
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        from paddleocr import PaddleOCR  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            f"PaddleOCR needs extra packages (missing: {e.name or e}). "
            "Install them with: pip install 'frameshot[ocr-paddle]' "
            "(pulls paddlepaddle, paddleocr, opencv for cv2, numpy). "
                "Or switch OCR engine to tesseract in Settings.") from e

    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("PaddleOCR: could not decode image.")
    ocr = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
    result = ocr.ocr(img, cls=True)
    lines: list[str] = []
    for page in result or []:
        for item in page or []:
            try:
                lines.append(str(item[1][0]))
            except Exception:  # noqa: BLE001
                continue
    return "\n".join(lines).strip()


class OCRWorker(QThread):
    """Runs OCR off the GUI thread."""

    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, png_bytes: bytes, engine: str, lang: str = "en",
                 parent=None):
        super().__init__(parent)
        self._png = png_bytes
        self._engine = engine
        self._lang = lang

    def run(self):  # noqa: D102
        try:
            text = ocr_png_bytes(self._png, self._engine, self._lang)
            self.finished.emit(text)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
