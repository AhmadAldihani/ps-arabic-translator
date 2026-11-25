"""Keeps Tarjemni.exe up to date by itself: checks the latest GitHub release when it starts,
downloads the new version and restarts into it."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

from .version import VERSION

REPO = "AhmadAldihani/ps-arabic-translator"
LATEST = f"https://github.com/{REPO}/releases/latest/download"


def latest_versions(timeout: float = 8.0) -> dict:
    req = urllib.request.Request(f"{LATEST}/version.json", headers={"User-Agent": "Tarjemni"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Updater:
    def __init__(self):
        self.current = VERSION
        self.latest: dict = {}
        self.status = "idle"   # idle | checking | up_to_date | downloading | restarting | error | dev
        self.error: str | None = None

    def state(self) -> dict:
        return {"current": self.current, "latest": self.latest, "status": self.status, "error": self.error}

    def check_async(self, can_restart):
        threading.Thread(target=self._run, args=(can_restart,), daemon=True).start()

    def _run(self, can_restart):
        self.status = "checking"
        try:
            self.latest = latest_versions()
        except Exception as e:  # noqa: BLE001 - offline is fine
            self.status, self.error = "error", str(e)[:200]
            return
        newest = int(self.latest.get("pc", 0))
        if not getattr(sys, "frozen", False) or self.current == 0:
            self.status = "dev"
            return
        if newest <= self.current:
            self.status = "up_to_date"
            return
        self.status = "downloading"
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{LATEST}/Tarjemni-Windows.zip",
                                                               headers={"User-Agent": "Tarjemni"}), timeout=120) as r:
                data = r.read()
            new_exe = Path(tempfile.gettempdir()) / f"Tarjemni-{newest}.exe"
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                new_exe.write_bytes(z.read("Tarjemni.exe"))
        except Exception as e:  # noqa: BLE001
            self.status, self.error = "error", str(e)[:200]
            return
        # wait until no translation is running, then swap and restart
        import time
        while not can_restart():
            time.sleep(2)
        self.status = "restarting"
        restart_into(new_exe)


def restart_into(new_exe: Path):
    current = Path(sys.executable)
    bat = Path(tempfile.gettempdir()) / "tarjemni-update.bat"
    bat.write_text(
        "@echo off\r\n"
        "ping 127.0.0.1 -n 3 > nul\r\n"
        ":retry\r\n"
        f'copy /y "{new_exe}" "{current}" > nul || (ping 127.0.0.1 -n 2 > nul & goto retry)\r\n'
        f'start "" "{current}"\r\n'
        f'del "{new_exe}"\r\n'
        'del "%~f0"\r\n', "utf-8")
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True)
    os._exit(0)
