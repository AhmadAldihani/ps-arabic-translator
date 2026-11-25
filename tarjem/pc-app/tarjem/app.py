"""Tarjemni (ترجمني) for Windows: a small local web app (opens in your browser) that drives everything."""
from __future__ import annotations

import json
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import adb, capture
from .config import PRESETS, Config, apply_calib, data_dir, load_overrides, save_overrides
from .engine import Engine
from .translate import Translator, ai_translate
from .tvlink import SERVER_PORT, TvLink, discover
from .updater import Updater
from .version import VERSION

UI_PORT = 47880
FONT_FILES = {"cairo": "cairo.ttf", "tajawal": "tajawal-bold.ttf", "tajawal-regular": "tajawal-regular.ttf",
              "plex": "plex-bold.ttf", "plex-regular": "plex-regular.ttf", "naskh": "naskh.ttf"}


def resource(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "tarjem" / name
    return p if p.exists() else Path(__file__).resolve().parent / name


def default_ocr_factory(lang: str):
    from .ocr import WindowsOcr
    return WindowsOcr(lang)


class App:
    def __init__(self, ocr_factory=default_ocr_factory):
        self.cfg = Config()
        self.tv = TvLink(client_name=socket.gethostname()[:40] or "laptop")
        self.translator = Translator(load_overrides(), on_overrides_changed=save_overrides,
                                     cache_file=data_dir() / "translations.json")
        self.apply_translation_settings()
        self.engine = Engine(self.cfg, self.tv, self.translator, ocr_factory)
        self.updater = Updater()
        self.last_discovery: list[dict] = []
        self.adb_log = ""
        if self.cfg.data.get("tv_ip"):
            self.connect(self.cfg.data["tv_ip"])

    def apply_translation_settings(self):
        ai = self.cfg.data["ai"]
        if ai.get("provider") in ("gemini", "claude") and ai.get("key"):
            provider, key, model = ai["provider"], ai["key"], ai.get("model", "")
            self.translator.set_ai(lambda system, user: ai_translate(provider, key, model, system, user))
        else:
            self.translator.set_ai(None)
        self.translator.dialect = self.cfg.data.get("dialect", "msa")
        self.translator.glossary = dict(self.cfg.data.get("glossary", {}))

    def connect(self, ip: str, port: int = SERVER_PORT):
        ip = ip.strip()
        self.cfg.update({"tv_ip": ip})
        self.tv.set_target(ip or None, port, on_connect=self.push_style)
        if ip:
            threading.Thread(target=lambda: self.tv.send({"t": "ping"}), daemon=True).start()

    def push_style(self):
        self.tv.send({"t": "style", "style": self.cfg.data["style"]})

    def calib_preview(self) -> bool:
        """Draw boxes where the English subtitles are right now (or the search area), for alignment."""
        rects = self.engine.current_rects()
        if not rects:
            x, y, w, h = self.cfg.region()
            rects = [[x + w * 0.2, y + h * 0.55, w * 0.6, h * 0.3]]
        calib = self.cfg.data["calib"]
        items = [{"rect": apply_calib(r, calib), "lines": [{"t": "مربع الضبط — لازم يغطي الترجمة الإنجليزية بالضبط"}]}
                 for r in rects]
        return self.tv.send({"t": "show", "items": items, "ttl": 8000})

    def state(self) -> dict:
        s = self.engine.snapshot()
        s.update({
            "version": VERSION,
            "update": self.updater.state(),
            "presets": list(PRESETS),
            "ai_error": self.translator.last_ai_error,
            "has_ai": self.translator.has_ai,
            "config": self.cfg.data,
            "tv": {
                "ip": self.tv.host, "connected": self.tv.connected, "name": self.tv.tv_name,
                "overlay": self.tv.tv_overlay, "error": None if self.tv.connected else self.tv.last_error,
                "version": self.tv.tv_version,
            },
            "discovered": self.last_discovery,
            "adb_log": self.adb_log,
        })
        return s

    def handle(self, path: str, body: dict) -> dict:
        if path == "/api/discover":
            self.last_discovery = discover(2.5)
            if len(self.last_discovery) == 1 and not self.tv.connected:
                tv = self.last_discovery[0]
                self.connect(tv["ip"], int(tv.get("port", SERVER_PORT)))
            return {"found": self.last_discovery}
        if path == "/api/connect":
            self.connect(body.get("ip", ""), int(body.get("port", SERVER_PORT)))
            return {"ok": True}
        if path == "/api/config":
            self.cfg.update(body)
            if {"ai", "dialect", "glossary"} & set(body):
                self.apply_translation_settings()
            if "preset" in body:
                body = {**body, "style": self.cfg.data["style"]}
            if "style" in body:
                self.push_style()
            if "style" in body or "calib" in body:
                self.engine.resend_current()
            if "calib" in body and body.get("preview"):
                self.calib_preview()
            return {"ok": True}
        if path == "/api/ai_test":
            self.apply_translation_settings()
            if not self.translator.has_ai:
                return {"ok": False, "error": "اختر المزوّد واكتب المفتاح"}
            from .translate import build_prompt
            system, user = build_prompt("Hold up, Lucia. We ain't done yet.", "Jason", [], self.translator.glossary,
                                        self.translator.dialect)
            try:
                ai = self.cfg.data["ai"]
                return {"ok": True, "text": ai_translate(ai["provider"], ai["key"], ai.get("model", ""), system, user)}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        if path == "/api/tv_update":
            return {"ok": self.tv.send({"t": "update"})}
        if path == "/api/calib_show":
            return {"ok": self.calib_preview()}
        if path == "/api/start":
            self.engine.start()
            return {"ok": True}
        if path == "/api/stop":
            self.engine.stop()
            return {"ok": True}
        if path == "/api/test":
            self.push_style()
            ok = self.tv.send({"t": "show", "ttl": 7000, "items": [
                {"rect": [0.3, 0.72, 0.4, 0.045], "lh": 0.04, "lines": [{"s": "جيسون", "t": "توقفي يا لوسيا!"}]},
                {"rect": [0.25, 0.80, 0.5, 0.09], "lh": 0.04, "lines": [{"s": "لوسيا", "t": "ما راح أوقف، لازم نخلص الحين."},
                                                                         {"t": "هذي تجربة للترجمة العربية ✓"}]}]})
            return {"ok": ok}
        if path == "/api/edit":
            return {"ok": self.engine.edit(int(body.get("id", 0)), str(body.get("text", "")))}
        if path == "/api/adb_grant":
            ip = body.get("ip") or self.tv.host or ""
            ok, log = adb.grant_overlay(ip, body.get("pair_address", ""), body.get("pair_code", ""))
            self.adb_log = log
            return {"ok": ok, "log": log}
        return {"error": "unknown"}


def selftest() -> dict:
    """Checks the Windows OCR on a generated subtitle; used by the build and for support."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        from .ocr import WindowsOcr
        img = Image.new("RGB", (1280, 200), (20, 30, 25))
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 36)
        except OSError:
            font = ImageFont.load_default()
        ImageDraw.Draw(img).text((280, 80), "Get in the car right now", font=font, fill=(255, 255, 255))
        text = " ".join(l.text for l in WindowsOcr("en").read(img))
        return {"ocr_ok": "car" in text.lower(), "ocr_text": text}
    except Exception as e:  # noqa: BLE001
        return {"ocr_ok": False, "error": f"{type(e).__name__}: {e}"}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._send(200, resource("ui.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(app.state())
            elif path.startswith("/fonts/"):
                name = path.rsplit("/", 1)[-1].removesuffix(".ttf")
                f = resource("fonts/" + FONT_FILES.get(name, "none"))
                if f.exists():
                    self._send(200, f.read_bytes(), "font/ttf")
                else:
                    self._json({"error": "no font"}, 404)
            elif path == "/api/selftest":
                self._json(selftest())
            elif path == "/api/windows":
                self._json(capture.list_windows())
            elif path == "/api/preview.jpg":
                try:
                    jpg = app.engine.preview_jpeg()
                except Exception as e:  # noqa: BLE001
                    return self._json({"error": str(e)}, 500)
                if jpg:
                    self._send(200, jpg, "image/jpeg")
                else:
                    self._json({"error": "no window"}, 404)
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            # Only accept requests from this computer's own page.
            origin = self.headers.get("Origin", "")
            if origin and not origin.startswith(("http://127.0.0.1", "http://localhost")):
                return self._json({"error": "forbidden"}, 403)
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                body = {}
            try:
                self._json(app.handle(self.path.split("?")[0], body))
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    return Handler


def main():
    if sys.platform == "win32":
        try:  # Arabic in the console window
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    app = App()
    server = None
    for port in range(UI_PORT, UI_PORT + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
            break
        except OSError:
            continue
    if server is None:
        print("Could not open a local port for the interface.")
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print("=" * 60)
    print(f" Tarjemni (ترجمني) v{VERSION} — Arabic subtitles for PlayStation")
    print(f" Interface: {url}")
    print(" Keep this window open while you play. Close it to quit.")
    print("=" * 60)
    app.updater.check_async(lambda: not app.engine.running)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.engine.stop()
        app.translator.save()
        app.tv.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
