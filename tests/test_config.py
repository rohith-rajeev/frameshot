"""Offline tests: settings roundtrip + hotkey normalization (no GUI, no gi)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from frameshot.background import _norm_binding  # noqa: E402
from frameshot.config import FrameshotSettings  # noqa: E402


def test_settings_roundtrip(tmp_path):
    p = tmp_path / "settings.ini"
    s = FrameshotSettings.load(p)
    assert s.save_to_disk is False
    s.save_to_disk = True
    s.save_dir = "/tmp/shots"
    s.ocr_lang = "de"
    s.portal_interactive_fallback = True
    s.save(p)
    s2 = FrameshotSettings.load(p)
    assert (s2.save_to_disk, s2.save_dir, s2.ocr_lang,
            s2.portal_interactive_fallback) == (
        True, "/tmp/shots", "de", True)


def test_filename_template_survives_percent_signs(tmp_path):
    # regression: configparser interpolation choked on %Y%m%d
    p = tmp_path / "settings.ini"
    s = FrameshotSettings.load(p)
    s.save(p)
    assert FrameshotSettings.load(p).filename_template == s.filename_template


def test_norm_binding_aliases():
    assert _norm_binding("<Primary><Shift>f") == _norm_binding("<Ctrl><Shift>F")
    assert _norm_binding("<Primary><Shift>g") != _norm_binding("<Primary><Shift>f")
    assert _norm_binding("<Shift><Super>F") == _norm_binding("<Super><Shift>f")
