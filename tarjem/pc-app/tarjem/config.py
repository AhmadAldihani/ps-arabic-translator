"""Settings saved in %APPDATA%\\Tarjem (or ~/.tarjem elsewhere)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

DEFAULTS = {
    "tv_ip": "",
    "window_title": "",
    # Where to look for subtitles: [x, y, w, h] as fractions of the game picture.
    "region": [0.10, 0.70, 0.80, 0.28],
    "interval": 0.3,
    "source_lang": "en",
    "centered_only": True,
    "style": {
        "size": 34, "fg": "#FFFFFF", "bg": "#101018", "bgAlpha": 0.88, "font": "sans",
        "bold": True, "placement": "cover", "radius": 14, "bottomMargin": 0.07, "maxWidth": 0.86,
        "outline": True,
    },
}


def data_dir() -> Path:
    base = os.environ.get("APPDATA")
    d = Path(base) / "Tarjem" if base else Path.home() / ".tarjem"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "config.json"
        self._lock = threading.Lock()
        self.data = json.loads(json.dumps(DEFAULTS))
        try:
            saved = json.loads(self.path.read_text("utf-8"))
            self.update(saved, save=False)
        except (OSError, ValueError):
            pass

    def update(self, patch: dict, save: bool = True):
        with self._lock:
            for k, v in patch.items():
                if k not in DEFAULTS:
                    continue
                if k == "style" and isinstance(v, dict):
                    self.data["style"].update({sk: sv for sk, sv in v.items() if sk in DEFAULTS["style"]})
                elif k == "region":
                    if isinstance(v, (list, tuple)) and len(v) == 4:
                        x, y, w, h = (float(t) for t in v)
                        x, y = min(max(x, 0.0), 0.95), min(max(y, 0.0), 0.95)
                        w, h = min(max(w, 0.05), 1.0 - x), min(max(h, 0.04), 1.0 - y)
                        self.data["region"] = [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]
                elif k == "interval":
                    self.data[k] = min(max(float(v), 0.15), 2.0)
                else:
                    self.data[k] = v
            if save:
                self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")

    def region(self) -> tuple[float, float, float, float]:
        x, y, w, h = self.data["region"]
        return float(x), float(y), float(w), float(h)


def load_overrides() -> dict[str, str]:
    try:
        return json.loads((data_dir() / "corrections.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_overrides(d: dict[str, str]):
    (data_dir() / "corrections.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
