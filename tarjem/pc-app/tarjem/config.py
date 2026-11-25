"""Settings saved in %APPDATA%\\Tarjemni (or ~/.tarjemni elsewhere)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .translate import GTA6_GLOSSARY

STYLE_DEFAULTS = {
    "font": "cairo",            # cairo | tajawal | plex | naskh | system
    "autoSize": True,           # match the English subtitle's size
    "sizeScale": 1.0,           # x the English size when autoSize
    "size": 34,                 # px on a 1080p screen when not autoSize
    "bold": True,
    "fg": "#FFFFFF",
    "bg": "#0B0F1A",
    "bgAlpha": 0.9,
    "radius": 12,
    "padX": 18,
    "padY": 8,
    "outline": False,
    "outlineColor": "#000000",
    "outlineWidth": 4,
    "shadow": True,
    "lineSpacing": 1.12,
    "speaker": "#F5B841",
    "speakerBold": True,
    "speakerOwnLine": False,
    "placement": "cover",       # cover | bottom | top
    "widthMode": "match",       # match (as wide as the English) | fit (as wide as the Arabic)
    "maxWidth": 0.86,
    "bottomMargin": 0.07,
}

PRESETS = {
    "classic": {"font": "cairo", "fg": "#FFFFFF", "bg": "#0B0F1A", "bgAlpha": 0.9, "radius": 12, "outline": False, "shadow": True, "speaker": "#F5B841"},
    "cinema": {"font": "tajawal", "fg": "#FFFFFF", "bg": "#000000", "bgAlpha": 0.0, "outline": True, "outlineWidth": 5, "outlineColor": "#000000", "shadow": True, "speaker": "#FFD54A"},
    "netflix": {"font": "plex", "fg": "#FFFFFF", "bg": "#000000", "bgAlpha": 0.6, "radius": 4, "outline": False, "shadow": True, "speaker": "#E50914"},
    "gta": {"font": "cairo", "fg": "#FFFFFF", "bg": "#1A0B2E", "bgAlpha": 0.85, "radius": 16, "outline": False, "shadow": True, "speaker": "#FF5FA2"},
    "yellow": {"font": "naskh", "fg": "#FFE14D", "bg": "#000000", "bgAlpha": 0.55, "radius": 8, "outline": True, "outlineWidth": 3, "speaker": "#7FE3FF"},
}

DEFAULTS = {
    "tv_ip": "",
    "window_title": "",
    # Where to look for subtitles: [x, y, w, h] as fractions of the game picture.
    "region": [0.10, 0.62, 0.80, 0.36],
    "interval": 0.15,
    "source_lang": "en",
    "centered_only": True,
    "colour_names": True,       # detect a name shown in a different colour
    # Fine alignment of the Arabic box with the TV picture (TV overscan etc.).
    "calib": {"dx": 0.0, "dy": 0.0, "zoom": 1.0},
    "style": dict(STYLE_DEFAULTS),
    "ai": {"provider": "", "key": "", "model": ""},   # provider: "" | gemini | claude
    "dialect": "msa",
    "glossary": dict(GTA6_GLOSSARY),
}


def data_dir() -> Path:
    base = os.environ.get("APPDATA")
    d = Path(base) / "Tarjemni" if base else Path.home() / ".tarjemni"
    d.mkdir(parents=True, exist_ok=True)
    # carry over settings from the first version (Tarjem)
    old = Path(base) / "Tarjem" if base else Path.home() / ".tarjem"
    if old.exists() and not (d / "config.json").exists():
        for name in ("config.json", "corrections.json"):
            try:
                (d / name).write_bytes((old / name).read_bytes())
            except OSError:
                pass
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
                if k == "preset" and v in PRESETS:
                    self.data["style"].update(PRESETS[v])
                    continue
                if k not in DEFAULTS:
                    continue
                if k == "calib" and isinstance(v, dict):
                    c = self.data["calib"]
                    c["dx"] = min(max(float(v.get("dx", c["dx"])), -0.2), 0.2)
                    c["dy"] = min(max(float(v.get("dy", c["dy"])), -0.2), 0.2)
                    c["zoom"] = min(max(float(v.get("zoom", c["zoom"])), 0.8), 1.2)
                elif k == "style" and isinstance(v, dict):
                    self.data["style"].update({sk: sv for sk, sv in v.items() if sk in STYLE_DEFAULTS})
                elif k == "ai" and isinstance(v, dict):
                    self.data["ai"].update({ak: str(av).strip() for ak, av in v.items() if ak in ("provider", "key", "model")})
                elif k == "glossary" and isinstance(v, dict):
                    self.data["glossary"] = {str(a).strip(): str(b).strip() for a, b in v.items() if str(a).strip() and str(b).strip()}
                elif k == "region":
                    if isinstance(v, (list, tuple)) and len(v) == 4:
                        x, y, w, h = (float(t) for t in v)
                        x, y = min(max(x, 0.0), 0.95), min(max(y, 0.0), 0.95)
                        w, h = min(max(w, 0.05), 1.0 - x), min(max(h, 0.04), 1.0 - y)
                        self.data["region"] = [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]
                elif k == "interval":
                    self.data[k] = min(max(float(v), 0.08), 2.0)
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


def apply_calib(rect: list[float], calib: dict) -> list[float]:
    """Game-picture fractions -> TV screen fractions (zoom about the centre, then shift)."""
    z, dx, dy = float(calib.get("zoom", 1)), float(calib.get("dx", 0)), float(calib.get("dy", 0))
    x, y, w, h = rect
    return [round(0.5 + (x - 0.5) * z + dx, 4), round(0.5 + (y - 0.5) * z + dy, 4), round(w * z, 4), round(h * z, 4)]
