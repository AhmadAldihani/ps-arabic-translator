"""The live loop: grab the Remote Play picture, read the subtitles, translate, send to the TV."""
from __future__ import annotations

import io
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from . import capture
from .config import Config, apply_calib
from .extract import Subtitle, extract_all, similarity
from .tvlink import TvLink
from .translate import Translator

STABLE_SIMILARITY = 0.88   # two reads this close = the subtitles have settled
SAME_SIMILARITY = 0.80     # this close to what is on the TV = OCR jitter, not new dialogue
MISSES_BEFORE_CLEAR = 3
TTL_MS = 4000


class Block:
    """One subtitle block as read from the game, ready to be (re)translated and drawn."""

    def __init__(self, sub: Subtitle, rect: list[float]):
        self.sub = sub
        self.rect = rect  # fractions of the game picture
        self.utterances = sub.utterances


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
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="send")
        self._tpool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="translate")
        self._lock = threading.Lock()
        self._video = capture.VideoArea()

        self.running = False
        self.status = "متوقف"
        self.error: str | None = None
        self.fps = 0.0
        self.history: deque[dict] = deque(maxlen=40)
        self._next_id = 1
        self._seen: set[str] = set()

        self._candidate: str | None = None
        self._shown_key: str | None = None
        self._shown_blocks: list[Block] | None = None
        self._shown_ready = False
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
        self._shown_key = None
        self._shown_blocks = None
        self.tv.send({"t": "clear"})

    # -- helpers used by the UI ------------------------------------------------------

    def preview_jpeg(self) -> bytes | None:
        """The game picture (black bars removed) for the region picker."""
        img = self._last_frame if self.running else None
        if img is None:
            hwnd = capture.find_window(self.cfg.data.get("window_title"))
            frame = capture.capture_window(hwnd) if hwnd else None
            if frame is None:
                return None
            gx, gy, gw, gh = self._video.update(frame)
            img = frame.crop((gx, gy, gx + gw, gy + gh))
        small = img.copy()
        small.thumbnail((960, 540))
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=80)
        return buf.getvalue()

    def current_rects(self) -> list[list[float]]:
        """Where the subtitles currently on screen are (game fractions), for calibration."""
        blocks = self._shown_blocks or []
        return [b.rect for b in blocks]

    def resend_current(self):
        """After a style/calibration change or an edited translation, refresh what the TV shows."""
        blocks = self._shown_blocks
        if blocks and self._shown_ready:
            self._pool.submit(self._translate_and_send, blocks, self._shown_key, False)

    def edit(self, item_id: int, arabic: str) -> bool:
        with self._lock:
            item = next((h for h in self.history if h["id"] == item_id), None)
        if item is None:
            return False
        self.translator.set_override(item["src"], arabic)
        if arabic.strip():
            item["ar"] = arabic.strip()
            item["edited"] = True
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

        gx, gy, gw, gh = self._video.update(frame)
        game = frame.crop((gx, gy, gx + gw, gy + gh))
        self._last_frame = game
        rx, ry, rw, rh = self.cfg.region()
        x0, y0 = int(rx * gw), int(ry * gh)
        x1, y1 = max(x0 + 8, int((rx + rw) * gw)), max(y0 + 8, int((ry + rh) * gh))
        crop = game.crop((x0, y0, x1, y1))

        lines = self._ocr.read(crop)
        subs = extract_all(lines, crop.width, gh, bool(self.cfg.data.get("centered_only", True)))
        self.status = "شغّال" if self.tv.connected else "شغّال — بس التلفزيون مو متصل"
        self.error = None

        if not subs:
            self._candidate = None
            self._misses += 1
            if self._misses >= MISSES_BEFORE_CLEAR and self._shown_key is not None:
                self._shown_key = None
                self._shown_blocks = None
                self.tv.send({"t": "clear"})
            return
        self._misses = 0

        blocks = [Block(s, [(x0 + s.box.left) / gw, (y0 + s.box.top) / gh, s.box.width / gw, s.box.height / gh])
                  for s in subs]
        key = " || ".join(s.key for s in subs)

        if self._shown_key is not None and similarity(key, self._shown_key) >= SAME_SIMILARITY:
            if time.time() - self._last_keep > 1.0:
                self.tv.send({"t": "keep", "ttl": TTL_MS})
                self._last_keep = time.time()
            return

        candidate, self._candidate = self._candidate, key
        if candidate is None or similarity(key, candidate) < STABLE_SIMILARITY:
            return  # wait one more read: skips fades and typewriter text

        self._shown_key = key
        self._shown_blocks = blocks
        self._shown_ready = False
        self._pool.submit(self._translate_and_send, blocks, key, True)

    def _translate_and_send(self, blocks: list[Block], key: str | None, record: bool):
        try:
            # Translate every spoken line (and each character name) in parallel; the cache
            # makes names and repeated lines instant.
            jobs = []
            for b in blocks:
                for sp, body in b.utterances:
                    jobs.append((sp, body, self._tpool.submit(self.translator.translate, body),
                                 self._tpool.submit(self.translator.translate, sp) if sp else None))
            results = [(sp, body, f.result(timeout=15), (g.result(timeout=15) if g else None)) for sp, body, f, g in jobs]
        except Exception as e:  # noqa: BLE001
            self.error = f"الترجمة: {e}"
            if self._shown_key == key:
                self._shown_key = None  # retry on the next read
            return

        items, i = [], 0
        for b in blocks:
            lines = []
            for _ in b.utterances:
                sp, body, ar, sp_ar = results[i]
                i += 1
                if ar:
                    lines.append({"s": sp_ar or sp, "t": ar} if sp else {"t": ar})
                if record:
                    self._remember(sp, body, ar, sp_ar)
            if lines:
                items.append({"rect": apply_calib(b.rect, self.cfg.data["calib"]), "lines": lines})

        if self._shown_key != key or not items:
            return
        self._shown_ready = True
        self.tv.send({"t": "show", "items": items, "ttl": TTL_MS})
        self._last_keep = time.time()

    def _remember(self, sp: str | None, body: str, ar: str, sp_ar: str | None):
        with self._lock:
            sig = (sp or "") + "|" + body
            if sig in self._seen and self.history and any(h["src"] == body for h in list(self.history)[:6]):
                return
            self._seen.add(sig)
            self.history.appendleft({
                "id": self._next_id, "src": body, "en": (f"{sp}: " if sp else "") + body,
                "ar": ar, "speaker": sp_ar or sp, "t": time.strftime("%H:%M:%S"),
            })
            self._next_id += 1

    def snapshot(self) -> dict:
        with self._lock:
            hist = [dict(h) for h in self.history]
        return {
            "running": self.running, "status": self.status, "error": self.error,
            "fps": round(self.fps, 1), "history": hist,
        }
