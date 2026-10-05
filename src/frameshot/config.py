"""Persistent settings. Clipboard-first by default (pointer #5)."""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path


def default_config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "frameshot"


def default_save_dir() -> Path:
    pictures = Path.home() / "Pictures" / "frameshot"
    return pictures


@dataclass
class FrameshotSettings:
    # pointer #5: clipboard-first; disk save is opt-in
    save_to_disk: bool = False
    save_dir: str = field(default_factory=lambda: str(default_save_dir()))
    filename_template: str = "frameshot-%Y%m%d-%H%M%S.png"
    image_format: str = "png"  # png | jpg
    jpg_quality: int = 90

    hotkey: str = "Ctrl+Shift+F"  # pointer #1 default; applied by setup script

    ocr_engine: str = "auto"  # auto | paddle | tesseract | off
    ocr_lang: str = "en"

    # GNOME may deny silent screenshots (portal response=2); when True,
    # frameshot falls back to the compositor's native screenshot UI instead
    # of failing. Default OFF: frameshot never pops another tool's UI
    # uninvited — on GNOME install the shell extension instead
    # (shell-extension/frameshot-capture@frameshot.local), which needs no portal.
    # The fallback image is user-composed, so frameshot then skips its own
    # selection overlay and goes straight to annotate.
    portal_interactive_fallback: bool = False

    pen_color: str = "#ff2d2d"
    pen_width: int = 3
    font_size: int = 18
    blur_strength: int = 16

    _path: Path | None = None

    @classmethod
    def load(cls, path: Path | str | None = None) -> "FrameshotSettings":
        cfg_path = Path(path) if path is not None else (default_config_dir() / "settings.ini")
        s = cls(_path=cfg_path)
        if cfg_path.exists():
            cp = configparser.ConfigParser(interpolation=None)
            cp.read(cfg_path)
            g = cp["frameshot"] if "frameshot" in cp else {}
            s.save_to_disk = g.getboolean("save_to_disk", fallback=s.save_to_disk)
            s.save_dir = g.get("save_dir", fallback=s.save_dir)
            s.filename_template = g.get("filename_template", fallback=s.filename_template)
            s.image_format = g.get("image_format", fallback=s.image_format)
            s.jpg_quality = g.getint("jpg_quality", fallback=s.jpg_quality)
            s.hotkey = g.get("hotkey", fallback=s.hotkey)
            s.ocr_engine = g.get("ocr_engine", fallback=s.ocr_engine)
            s.ocr_lang = g.get("ocr_lang", fallback=s.ocr_lang)
            s.portal_interactive_fallback = g.getboolean(
                "portal_interactive_fallback",
                fallback=s.portal_interactive_fallback)
            s.pen_color = g.get("pen_color", fallback=s.pen_color)
            s.pen_width = g.getint("pen_width", fallback=s.pen_width)
            s.font_size = g.getint("font_size", fallback=s.font_size)
            s.blur_strength = g.getint("blur_strength", fallback=s.blur_strength)
        return s

    def save(self, path: Path | str | None = None) -> Path:
        cfg_path = Path(path) if path is not None else (
            self._path or (default_config_dir() / "settings.ini"))
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cp = configparser.ConfigParser(interpolation=None)
        cp["frameshot"] = {
            "save_to_disk": str(self.save_to_disk),
            "save_dir": self.save_dir,
            "filename_template": self.filename_template,
            "image_format": self.image_format,
            "jpg_quality": str(self.jpg_quality),
            "hotkey": self.hotkey,
            "ocr_engine": self.ocr_engine,
            "ocr_lang": self.ocr_lang,
            "portal_interactive_fallback": str(self.portal_interactive_fallback),
            "pen_color": self.pen_color,
            "pen_width": str(self.pen_width),
            "font_size": str(self.font_size),
            "blur_strength": str(self.blur_strength),
        }
        with open(cfg_path, "w") as f:
            cp.write(f)
        self._path = cfg_path
        return cfg_path
