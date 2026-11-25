"""English (or another language) -> Arabic translation with a cache and user corrections."""
from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Callable

from .extract import normalize

GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"


def parse_google(payload: str) -> str:
    """The free endpoint returns [[["translated","source",...], ...], ...]."""
    data = json.loads(payload)
    parts = data[0] or []
    return "".join(p[0] for p in parts if p and p[0]).strip()


def google_translate(text: str, source: str = "en", target: str = "ar", timeout: float = 6.0) -> str:
    q = urllib.parse.urlencode({"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text})
    req = urllib.request.Request(f"{GOOGLE_URL}?{q}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse_google(r.read().decode("utf-8"))


class Translator:
    """Thread-safe. User corrections (overrides) always win over the machine translation."""

    def __init__(self, overrides: dict[str, str] | None = None,
                 backend: Callable[[str, str, str], str] = google_translate,
                 on_overrides_changed: Callable[[dict[str, str]], None] | None = None):
        self._backend = backend
        self._overrides: dict[str, str] = dict(overrides or {})
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()
        self._on_changed = on_overrides_changed
        self.source = "en"
        self.target = "ar"

    def translate(self, text: str) -> str:
        key = normalize(text)
        with self._lock:
            if key in self._overrides:
                return self._overrides[key]
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        result = self._backend(text, self.source, self.target)
        with self._lock:
            self._cache[key] = result
            while len(self._cache) > 2000:
                self._cache.popitem(last=False)
        return result

    def set_override(self, source_text: str, arabic: str) -> None:
        key = normalize(source_text)
        with self._lock:
            if arabic.strip():
                self._overrides[key] = arabic.strip()
            else:
                self._overrides.pop(key, None)
            snapshot = dict(self._overrides)
        if self._on_changed:
            self._on_changed(snapshot)

    def overrides(self) -> dict[str, str]:
        with self._lock:
            return dict(self._overrides)
