"""Grant the TV app's "display over other apps" permission from the laptop with adb.

Many TVs hide that setting. With the TV's network debugging turned on, one command does it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PACKAGE = "com.tarjem.tv"


def adb_path() -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for cand in (base / "adb" / "adb.exe", Path(sys.executable).parent / "adb" / "adb.exe", base / "adb" / "adb"):
        if cand.exists():
            return str(cand)
    return "adb"


def _run(args: list[str], timeout: float = 15) -> tuple[int, str]:
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        p = subprocess.run([adb_path(), *args], capture_output=True, text=True, timeout=timeout, creationflags=flags)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 127, "adb not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out (did the TV show an 'Allow debugging' prompt?)"


def grant_overlay(tv_ip: str, pair_address: str = "", pair_code: str = "") -> tuple[bool, str]:
    """Returns (ok, log). pair_* are only for Android 11+ 'Wireless debugging' with a pairing code."""
    log = []
    if pair_address and pair_code:
        code, out = _run(["pair", pair_address, pair_code])
        log.append(f"pair: {out}")
        if code != 0 or "Successfully" not in out:
            return False, "\n".join(log)
    target = tv_ip if ":" in tv_ip else f"{tv_ip}:5555"
    code, out = _run(["connect", target], timeout=20)
    log.append(f"connect: {out}")
    if "connected" not in out.lower() or "cannot" in out.lower() or "failed" in out.lower():
        return False, "\n".join(log)
    code, out = _run(["-s", target, "shell", "appops", "set", PACKAGE, "SYSTEM_ALERT_WINDOW", "allow"])
    log.append(f"appops: {out or 'ok'}")
    if code != 0:
        return False, "\n".join(log)
    # Restart the TV app's service so it attaches the overlay right away.
    _run(["-s", target, "shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity"])
    return True, "\n".join(log)
