"""Self-update: version display, latest-release check, download, install.

No third-party deps — stdlib urllib + a QThread so the Settings page never
freezes on slow networks. Repository defaults to rohith-rajeev/frameshot (override
with FRAMESHOT_UPDATE_REPO="owner/repo").
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal

REPO = os.environ.get(
    "FRAMESHOT_UPDATE_REPO",
    os.environ.get("FRAME_UPDATE_REPO", "rohith-rajeev/frameshot"),  # pre-rename
)
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
TIMEOUT = 15


def parse_version(v: str) -> tuple[int, ...]:
    """'v1.2.3' / '1.2.3' -> (1, 2, 3). Non-numeric tails are ignored."""
    v = v.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in v.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "frameshot-updater",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def latest_release() -> dict:
    """{'tag': 'v0.2.0', 'name': ..., 'body': ..., 'assets': [{name, url}]}."""
    try:
        data = _get_json(API_LATEST)
    except Exception as e:  # noqa: BLE001  (HTTPError 404 = no releases yet)
        raise RuntimeError(
            f"Could not reach releases for {REPO}: {e}") from e
    return {
        "tag": str(data.get("tag_name", "")),
        "name": str(data.get("name", "")),
        "body": str(data.get("body", "")),
        "assets": [{"name": a.get("name", ""),
                    "url": a.get("browser_download_url", "")}
                   for a in data.get("assets", [])],
    }


def pick_asset(rel: dict) -> dict | None:
    """Prefer the platform bundle for this OS, else the wheel, else sdist."""
    assets = rel.get("assets", [])
    plat = "macos" if sys.platform == "darwin" else "linux"
    for a in assets:
        n = a["name"].lower()
        if plat in n and n.endswith((".tar.gz", ".zip")):
            return a
    for a in assets:
        if a["name"].endswith(".whl"):
            return a
    for a in assets:
        if a["name"].endswith(".tar.gz"):
            return a
    return None


def download_asset(url: str, dest_dir: str) -> str:
    name = url.rstrip("/").split("/")[-1] or "frameshot-update.bin"
    dest = os.path.join(dest_dir, name)
    req = urllib.request.Request(url, headers={"User-Agent": "frameshot-updater"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
    return dest


def pip_install(path: str) -> None:
    """Install the downloaded bundle into the running environment."""
    p = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade",
                        path],
                       capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        raise RuntimeError(f"pip install failed:\n{(p.stderr or p.stdout)[-2000:]}")


def restart_app(extra_args: list[str] | None = None) -> None:
    """Replace this process with a fresh `python -m frameshot`."""
    argv = [sys.executable, "-m", "frameshot", *(extra_args or [])]
    os.execv(sys.executable, argv)


class UpdateCheckWorker(QThread):
    """Fetch latest release off the GUI thread."""

    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self._current = current

    def run(self):  # noqa: D102
        try:
            rel = latest_release()
            rel["is_newer"] = is_newer(rel["tag"], self._current)
            self.done.emit(rel)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


def perform_update(parent_widget=None) -> str:
    """Blocking check→download→install used by tests/CLI. Returns installed tag."""
    from . import __version__
    rel = latest_release()
    if not is_newer(rel["tag"], __version__):
        return ""
    asset = pick_asset(rel)
    if asset is None:
        raise RuntimeError("Release has no downloadable assets.")
    with tempfile.TemporaryDirectory(prefix="frameshot-update-") as d:
        path = download_asset(asset["url"], d)
        pip_install(path)
    return rel["tag"]
