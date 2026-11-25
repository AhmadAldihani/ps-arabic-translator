"""Tests for: colour-coded speaker names, AI refinement, instant display, saved cache, line height."""
import time

from PIL import Image, ImageDraw

from tarjem import capture
from tarjem.config import Config, PRESETS
from tarjem.engine import Engine
from tarjem.extract import Box, Line, extract_all
from tarjem.speaker import mark_coloured_speaker
from tarjem.translate import Translator, build_prompt, clean_ai
from tarjem.tvlink import TvLink
from test_core import FakeTv


def _word_line(img, words):
    """words: [(text, colour, x0, x1)] drawn as solid bars (OCR boxes) on img."""
    d = ImageDraw.Draw(img)
    ws = []
    for text, col, x0, x1 in words:
        d.rectangle((x0 + 2, 104, x1 - 2, 126), fill=col)
        ws.append(Line(text, Box(x0, 100, x1, 130)))
    return Line(" ".join(w for w, *_ in words), Box(words[0][2], 100, words[-1][3], 130), tuple(ws))


def test_name_in_another_colour_becomes_speaker():
    img = Image.new("RGB", (800, 200), (10, 10, 10))
    line = _word_line(img, [("Jason", (255, 210, 40), 100, 180), ("stop", (240, 240, 240), 190, 250),
                            ("it,", (240, 240, 240), 260, 300), ("Lucia.", (240, 240, 240), 310, 400)])
    marked = mark_coloured_speaker(img, line)
    assert marked.text == "Jason: stop it, Lucia."
    subs = extract_all([marked], 800, 720, centered_only=False)
    assert subs[0].utterances == [("Jason", "stop it, Lucia.")]
    # all one colour: unchanged
    img2 = Image.new("RGB", (800, 200), (10, 10, 10))
    plain = _word_line(img2, [("Get", (240, 240, 240), 100, 160), ("in", (240, 240, 240), 170, 200), ("now", (240, 240, 240), 210, 270)])
    assert mark_coloured_speaker(img2, plain).text == "Get in now"


def test_ai_refines_and_cache_persists(tmp_path):
    calls = {"google": 0, "ai": 0}

    def google(t, s, d):
        calls["google"] += 1
        return "حرفي"

    def ai(system, user):
        calls["ai"] += 1
        assert "Grand Theft Auto VI" in system and "لوسيا" in system
        return '"طبيعي"'

    cache = tmp_path / "cache.json"
    t = Translator(backend=google, cache_file=cache, ai=ai)
    assert t.translate("Hold up, Lucia.") == "حرفي"
    assert t.refine("Hold up, Lucia.", "Jason") == "طبيعي"
    assert t.translate("hold up lucia") == "طبيعي"      # best answer now served instantly
    assert t.name("JASON") == "جيسون"
    t.save()
    t2 = Translator(backend=google, cache_file=cache)
    assert t2.translate("Hold up, Lucia.") == "طبيعي" and calls["google"] == 1


def test_prompt_and_presets():
    system, user = build_prompt("Get in!", "Lucia", [("Hi", "هلا")], {"Lucia": "لوسيا"}, "gulf")
    assert "Gulf" in system and "Speaker: Lucia" in user and "Hi => هلا" in user
    assert clean_ai('الترجمة: "يلا اركب!"') == "يلا اركب!"
    cfg = Config.__new__(Config)
    import threading, json
    from tarjem.config import DEFAULTS
    cfg._lock = threading.Lock(); cfg.data = json.loads(json.dumps(DEFAULTS)); cfg.path = None
    cfg.update({"preset": "cinema"}, save=False)
    assert cfg.data["style"]["outline"] is True and cfg.data["style"]["font"] == PRESETS["cinema"]["font"]


def test_instant_then_refined_on_tv(tmp_path, monkeypatch):
    tv = FakeTv()
    link = TvLink("pc")
    link.set_target("127.0.0.1", tv.port)
    cfg = Config(tmp_path / "c.json")
    cfg.update({"region": [0.0, 0.5, 1.0, 0.5], "interval": 0.1})
    frame = Image.new("RGB", (1280, 720))
    monkeypatch.setattr(capture, "find_window", lambda title: 1)
    monkeypatch.setattr(capture, "is_minimized", lambda h: False)
    monkeypatch.setattr(capture, "capture_window", lambda h: frame)
    monkeypatch.setattr(capture.VideoArea, "update", lambda self, img: (0, 0, img.width, img.height))

    class FakeOcr:
        def read(self, img):
            return [Line("Lucia: We gotta move.", Box(450, 250, 830, 290))]

    def slow_ai(system, user):
        time.sleep(0.3)
        return "لازم نتحرك."

    tr = Translator(backend=lambda t, s, d: {"We gotta move.": "علينا أن نتحرك."}.get(t, t), ai=slow_ai)
    eng = Engine(cfg, link, tr, lambda lang: FakeOcr())
    t0 = time.time()
    eng.start()
    deadline = time.time() + 5
    while len([m for m in tv.msgs if m["t"] == "show"]) < 2 and time.time() < deadline:
        time.sleep(0.02)
    eng.stop()
    shows = [m for m in tv.msgs if m["t"] == "show"]
    assert shows[0]["items"][0]["lines"] == [{"s": "لوسيا", "t": "علينا أن نتحرك."}]   # instant
    assert shows[1]["items"][0]["lines"] == [{"s": "لوسيا", "t": "لازم نتحرك."}]       # refined
    assert abs(shows[0]["items"][0]["lh"] - 40 / 720) < 0.002
    assert eng.snapshot()["history"][0]["ar"] == "لازم نتحرك."
    link.close()
