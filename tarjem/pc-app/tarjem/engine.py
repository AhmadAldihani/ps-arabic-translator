"""The live loop: grab the Remote Play picture, read the subtitle, translate, send to the TV."""
from __future__ import annotations

import io
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from . import capture
from .config import Config
from .extract import Subtitle, extract, similarity
from .tvlink import TvLink
from .translate import Translator

STABLE_SIMILARITY = 0.88   # two reads this close = the subtitle has settled
SAME_SIMILARITY = 0.80     # this close to what is on the TV = OCR jitter, not new dialogue
MISSES_BEFORE_CLEAR = 3
TTL_MS = 4000


class Engine:
    def __init__(self, cfg: Config, tv: TvLink, translator: Translator, ocr_factory):
        self.cfg = cfg
        self.tv = tv
        self.translator = translator
        self._ocr_factory = ocr_factory
        self._ocr = None
        self._ocr_lang = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="translate")
        self._lock = threading.Lock()

        self.running = False
        self.status = "متوقف"
        self.error: str | None = None
        self.fps = 0.0
        self.history: deque[dict] = deque(maxlen=40)
        self._next_id = 1

        self._candidate: str | None = None
        self._shown: Subtitle | None = None
        self._shown_text: str | None = None
        self._shown_rect: list[float] | None = None
        self._misses = 0
        self._last_keep = 0.0
        self._last_frame: Image.Image | None = None

    # -- control -----------------------------------------------------------------

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self.running = True
        self.error = None
        self._thread = threading.Thread(target=self._loop, name="engine", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.running = False
        self.status = "متوقف"
        self._shown = None
        self.tv.send({"t": "clear"})

    # -- helpers used by the UI ------------------------------------------------------

    def preview_jpeg(self) -> bytes | None:
        """The game picture (letterbox removed) for the region picker."""
        img = self._last_frame if self.running else None
        if img is None:
            hwnd = capture.find_window(self.cfg.data.get("window_title"))
            frame = capture.capture_window(hwnd) if hwnd else None
            if frame is None:
                return None
            gx, gy, gw, gh = capture.game_rect(*frame.size)
            img = frame.crop((gx, gy, gx + gw, gy + gh))
        small = img.copy()
        small.thumbnail((960, 540))
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=80)
        return buf.getvalue()

    def resend_current(self):
        """After a style change or an edited translation, refresh what the TV shows."""
        if self._shown is not None and self._shown_text:
            self._send_show(self._shown_text, self._shown)

    def edit(self, item_id: int, arabic: str):
        with self._lock:
            item = next((h for h in self.history if h["id"] == item_id), None)
        if item is None:
            return False
        self.translator.set_override(item["en"], arabic)
        item["ar"] = arabic.strip() or item["ar"]
        item["edited"] = True
        if self._shown is not None and self._shown.key == item.get("key"):
            self._shown_text = item["ar"]
            self.resend_current()
        return True

    # -- loop -----------------------------------------------------------------------

    def _loop(self):
        frames = 0
        t_fps = time.time()
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self._tick()
            except Exception as e:  # noqa: BLE001 - keep running, show the error in the UI
                self.error = f"{type(e).__name__}: {e}"
            frames += 1
            if time.time() - t_fps >= 2:
                self.fps = frames / (time.time() - t_fps)
                frames, t_fps = 0, time.time()
            interval = float(self.cfg.data.get("interval", 0.3))
            self._stop.wait(max(0.02, interval - (time.time() - t0)))

    def _tick(self):
        lang = self.cfg.data.get("source_lang", "en")
        if self._ocr is None or self._ocr_lang != lang:
            self._ocr = self._ocr_factory(lang)
            self._ocr_lang = lang
            self.translator.source = lang

        hwnd = capture.find_window(self.cfg.data.get("window_title"))
        if not hwnd:
            self.status = "ما لقيت نافذة PS Remote Play — شغّلها واتصل بالبلايستيشن"
            return
        if capture.is_minimized(hwnd):
            self.status = "نافذة Remote Play مصغّرة — رجّعها (تقدر تخليها خلف النوافذ الثانية)"
            return
        frame = capture.capture_window(hwnd)
        if frame is None:
            self.status = "تعذّر أخذ صورة من النافذة"
            return

        gx, gy, gw, gh = capture.game_rect(*frame.size)
        game = frame.crop((gx, gy, gx + gw, gy + gh))
        self._last_frame = game
        rx, ry, rw, rh = self.cfg.region()
        x0, y0 = int(rx * gw), int(ry * gh)
        x1, y1 = max(x0 + 8, int((rx + rw) * gw)), max(y0 + 8, int((ry + rh) * gh))
        crop = game.crop((x0, y0, x1, y1))

        lines = self._ocr.read(crop)
        sub = extract(lines, crop.width, gh, bool(self.cfg.data.get("centered_only", True)))
        self.status = "شغّال" if self.tv.connected else "شغّال — بس التلفزيون مو متصل"
        self.error = None

        if sub is None:
            self._candidate = None
            self._misses += 1
            if self._misses >= MISSES_BEFORE_CLEAR and self._shown is not None:
                self._shown = None
                self._shown_text = None
                self.tv.send({"t": "clear"})
            return
        self._misses = 0

        # The box in game-frame fractions, which is also where it sits on the TV.
        b = sub.box
        rect = [(x0 + b.left) / gw, (y0 + b.top) / gh, b.width / gw, b.height / gh]
        sub_rect = rect

        if self._shown is not None and similarity(sub.key, self._shown.key) >= SAME_SIMILARITY:
            if time.time() - self._last_keep > 1.0:
                self.tv.send({"t": "keep", "ttl": TTL_MS})
                self._last_keep = time.time()
            return

        candidate, self._candidate = self._candidate, sub.key
        if candidate is None or similarity(sub.key, candidate) < STABLE_SIMILARITY:
            return  # wait one more read: skips fades and typewriter text

        self._shown = sub
        self._shown_rect = sub_rect
        self._shown_text = None
        self._pool.submit(self._translate_and_send, sub, sub_rect)

    def _translate_and_send(self, sub: Subtitle, rect: list[float]):
        try:
            arabic = self.translator.translate(sub.text)
        except Exception as e:  # noqa: BLE001
            self.error = f"الترجمة: {e}"
            if self._shown is sub:
                self._shown = None  # retry on the next read
            return
        if not arabic:
            return
        with self._lock:
            item = {"id": self._next_id, "en": sub.text, "ar": arabic, "key": sub.key, "t": time.strftime("%H:%M:%S")}
            self._next_id += 1
            self.history.appendleft(item)
        if self._shown is sub:
            self._shown_text = arabic
            self._send_show(arabic, sub, rect)

    def _send_show(self, arabic: str, sub: Subtitle, rect: list[float] | None = None):
        rect = rect or self._shown_rect
        self.tv.send({"t": "show", "text": arabic, "rect": [round(v, 4) for v in rect] if rect else None, "ttl": TTL_MS})
        self._last_keep = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            hist = [dict(h) for h in self.history]
        for h in hist:
            h.pop("key", None)
        return {
            "running": self.running, "status": self.status, "error": self.error,
            "fps": round(self.fps, 1), "history": hist,
        }
