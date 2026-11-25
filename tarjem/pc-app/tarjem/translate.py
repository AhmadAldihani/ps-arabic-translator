"""Translation: instant Google translation, then (optionally) a natural, game-aware AI translation.

Order of preference for a line: your own correction > saved AI translation > saved quick translation > network.
Everything translated is saved to disk, so a line seen before appears instantly next time.
"""
from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Callable

from .extract import normalize

GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"

# Arabic spellings for GTA VI names (editable in the app's glossary).
GTA6_GLOSSARY = {
    "Jason": "جيسون", "Lucia": "لوسيا", "Vice City": "فايس سيتي", "Leonida": "ليونيدا",
    "Leonida Keys": "جزر ليونيدا", "Port Gellhorn": "بورت جيلهورن", "Ambrosia": "أمبروزيا",
    "Grassrivers": "غراس ريفرز", "Mount Kalaga": "جبل كالاغا", "Cal": "كال", "Boobie": "بوبي",
    "Raul": "راؤول", "Brian": "براين", "Drequan": "دريكوان", "Real Dimez": "ريل دايمز",
}

DIALECTS = {
    "msa": "Modern Standard Arabic (فصحى مبسطة), like professional Arabic subtitles on streaming services",
    "gulf": "Gulf Arabic (خليجي، لهجة كويتية/سعودية مفهومة), casual and natural like friends talking",
}


def parse_google(payload: str) -> str:
    """The free endpoint returns [[["translated","source",...], ...], ...]."""
    data = json.loads(payload)
    parts = data[0] or []
    return "".join(p[0] for p in parts if p and p[0]).strip()


def google_translate(text: str, source: str = "en", target: str = "ar", timeout: float = 4.0) -> str:
    q = urllib.parse.urlencode({"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text})
    req = urllib.request.Request(f"{GOOGLE_URL}?{q}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse_google(r.read().decode("utf-8"))


def build_prompt(text: str, speaker: str | None, context: list[tuple[str, str]], glossary: dict[str, str],
                 dialect: str, source_lang: str = "English") -> tuple[str, str]:
    names = "\n".join(f"- {k} = {v}" for k, v in glossary.items())
    system = (
        "You are the Arabic subtitle translator for the video game Grand Theft Auto VI (Rockstar Games), "
        "a crime story set in Vice City and the state of Leonida, following the couple Jason and Lucia.\n"
        f"Translate the player's {source_lang} subtitle into {DIALECTS.get(dialect, DIALECTS['msa'])}.\n"
        "Rules:\n"
        "- Translate the meaning and tone, never word for word. Slang, jokes and street talk become natural Arabic "
        "equivalents; insults and swearing become a milder but still punchy Arabic equivalent.\n"
        "- Keep it short and easy to read in a second or two, about as long as the original.\n"
        "- Use these spellings for names and places:\n" + names + "\n"
        "- Keep other proper names, brands and radio station names as they sound, in Arabic letters.\n"
        "- Output ONLY the Arabic subtitle text: no quotes, no speaker name, no notes."
    )
    parts = []
    if context:
        parts.append("Previous lines (for context only, do not translate again):")
        parts.extend(f"{src} => {ar}" for src, ar in context[-4:])
        parts.append("")
    if speaker:
        parts.append(f"Speaker: {speaker}")
    parts.append(f"Subtitle: {text}")
    return system, "\n".join(parts)


def _post_json(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ai_translate(provider: str, key: str, model: str, system: str, user: str, timeout: float = 8.0) -> str:
    if provider == "gemini":
        model = model or "gemini-flash-lite-latest"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={urllib.parse.quote(key)}"
        data = _post_json(url, {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 200},
        }, {}, timeout)
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
    if provider == "claude":
        data = _post_json("https://api.anthropic.com/v1/messages", {
            "model": model or "claude-haiku-5-5", "max_tokens": 200, "temperature": 0.4,
            "system": system, "messages": [{"role": "user", "content": user}],
        }, {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout)
        return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text").strip()
    raise ValueError(f"unknown provider {provider}")


def clean_ai(text: str) -> str:
    t = text.strip().strip('"“”«»').strip()
    for prefix in ("Subtitle:", "الترجمة:", "Translation:"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
    return t.strip('"“”«»').strip()


class Translator:
    """Thread-safe. User corrections always win."""

    def __init__(self, overrides: dict[str, str] | None = None,
                 backend: Callable[[str, str, str], str] = google_translate,
                 on_overrides_changed: Callable[[dict[str, str]], None] | None = None,
                 cache_file: Path | None = None,
                 ai: Callable[[str, str], str] | None = None):
        self._backend = backend
        self._ai = ai  # (system, user) -> arabic, or None when no AI key is set
        self._overrides: dict[str, str] = dict(overrides or {})
        self._quick: OrderedDict[str, str] = OrderedDict()
        self._best: dict[str, str] = {}
        self._lock = threading.Lock()
        self._on_changed = on_overrides_changed
        self._cache_file = cache_file
        self._dirty = 0
        self.source = "en"
        self.target = "ar"
        self.glossary: dict[str, str] = dict(GTA6_GLOSSARY)
        self.dialect = "msa"
        self.context: list[tuple[str, str]] = []
        self.last_ai_error: str | None = None
        if cache_file:
            try:
                saved = json.loads(cache_file.read_text("utf-8"))
                self._quick.update(saved.get("quick", {}))
                self._best.update(saved.get("best", {}))
            except (OSError, ValueError):
                pass

    # -- configuration --------------------------------------------------------------

    def set_ai(self, ai: Callable[[str, str], str] | None):
        self._ai = ai

    @property
    def has_ai(self) -> bool:
        return self._ai is not None

    # -- translation ----------------------------------------------------------------

    def translate(self, text: str) -> str:
        """Fastest good answer: correction, saved AI translation, saved/quick translation."""
        key = normalize(text)
        with self._lock:
            for table in (self._overrides, self._best, self._quick):
                if key in table:
                    if table is self._quick:
                        self._quick.move_to_end(key)
                    return table[key]
        result = self._backend(text, self.source, self.target)
        with self._lock:
            self._quick[key] = result
            while len(self._quick) > 5000:
                self._quick.popitem(last=False)
        self._mark_dirty()
        return result

    def has_best(self, text: str) -> bool:
        key = normalize(text)
        with self._lock:
            return key in self._overrides or key in self._best

    def refine(self, text: str, speaker: str | None = None) -> str | None:
        """Natural, game-aware translation from the AI (None when no AI or it failed)."""
        if self._ai is None:
            return None
        key = normalize(text)
        with self._lock:
            if key in self._overrides:
                return self._overrides[key]
            if key in self._best:
                return self._best[key]
            ctx = list(self.context)
        system, user = build_prompt(text, speaker, ctx, self.glossary, self.dialect)
        try:
            result = clean_ai(self._ai(system, user))
            self.last_ai_error = None
        except Exception as e:  # noqa: BLE001
            self.last_ai_error = f"{type(e).__name__}: {e}"[:200]
            return None
        if not result:
            return None
        with self._lock:
            self._best[key] = result
        self._mark_dirty()
        return result

    def name(self, speaker: str) -> str:
        """Arabic for a character name: glossary first (any letter case), else a cached translation."""
        for k, v in self.glossary.items():
            if k.lower() == speaker.lower():
                return v
        return self.translate(speaker.title() if speaker.isupper() else speaker)

    def remember_context(self, src: str, ar: str):
        with self._lock:
            self.context.append((src, ar))
            del self.context[:-6]

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

    # -- disk cache -----------------------------------------------------------------

    def _mark_dirty(self):
        self._dirty += 1
        if self._dirty >= 5:
            self.save()

    def save(self):
        if not self._cache_file:
            return
        with self._lock:
            data = {"quick": dict(self._quick), "best": dict(self._best)}
            self._dirty = 0
        try:
            tmp = self._cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
            tmp.replace(self._cache_file)
        except OSError:
            pass
