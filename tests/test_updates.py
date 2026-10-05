"""Offline tests for the self-update logic (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from frameshot.updates import is_newer, parse_version, pick_asset  # noqa: E402


def test_parse_version():
    assert parse_version("v0.2.0") == (0, 2, 0)
    assert parse_version("1.10.3") == (1, 10, 3)
    assert parse_version("2") == (2, 0, 0)
    assert parse_version("v1.2") == (1, 2, 0)


def test_is_newer():
    assert is_newer("v0.3.0", "0.2.0")
    assert is_newer("1.0.0", "0.9.9")
    assert not is_newer("v0.2.0", "0.2.0")
    assert not is_newer("v0.1.9", "0.2.0")


def _rel(*names):
    return {"assets": [{"name": n, "url": f"https://x/{n}"} for n in names]}


def test_pick_asset_prefers_platform_bundle():
    rel = _rel("frameshot-0.2.0.tar.gz", "frameshot-0.2.0-py3-none-any.whl",
               "frameshot-0.2.0-linux-x86_64.tar.gz",
               "frameshot-0.2.0-macos.tar.gz")
    if sys.platform == "darwin":
        assert pick_asset(rel)["name"] == "frameshot-0.2.0-macos.tar.gz"
    else:
        assert pick_asset(rel)["name"] == "frameshot-0.2.0-linux-x86_64.tar.gz"


def test_pick_asset_prefers_wheel_over_bare_sdist():
    # no platform bundle present: wheel beats a bare source tarball
    rel = _rel("frameshot-0.2.0.tar.gz", "frameshot-0.2.0-py3-none-any.whl")
    assert pick_asset(rel)["name"] == "frameshot-0.2.0-py3-none-any.whl"


def test_pick_asset_falls_back_to_wheel_then_sdist():
    assert pick_asset(_rel("a.whl", "a.tar.gz"))["name"] == "a.whl"
    assert pick_asset(_rel("a.tar.gz"))["name"] == "a.tar.gz"
    assert pick_asset({"assets": []}) is None
