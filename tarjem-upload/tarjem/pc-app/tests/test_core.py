import json
import socket
import threading
import time

from PIL import Image

from tarjem import capture
from tarjem.config import Config
from tarjem.engine import Engine
from tarjem.extract import Box, Line, extract, normalize, similarity, join_for_translation, clean_line
from tarjem.translate import Translator, parse_google
from tarjem.tvlink import TvLink


# ---------------------------------------------------------------- extract

def test_picks_centred_dialogue():
    lines = [
        Line("We have to leave before the", Box(400, 600, 880, 630)),
        Line("storm reaches the village.", Box(420, 636, 860, 666)),
        Line("Quest: Find Atreus", Box(20, 480, 260, 500)),
        Line("12:45", Box(600, 450, 680, 470)),
    ]
    s = extract(lines, 1280, 720, True)
    assert s.text == "We have to leave before the storm reaches the village."
    assert s.box == Box(400, 600, 880, 666)


def test_text_helpers():
    assert join_for_translation(["- Where are you?", "- Right here."]) == "- Where are you?\n- Right here."
    assert join_for_translation(["some-", "thing new"]) == "something new"
    assert clean_line("| don't know |") == "I don't know"
    a, b = normalize("We have to leave, before the storm!"), normalize("We have to Ieave before the storm")
    assert similarity(a, b) > 0.88
    assert similarity(a, normalize("Then we go north and find the boat.")) < 0.6
    assert extract([Line("x", Box(600, 600, 610, 630))], 1280, 720) is None


# ---------------------------------------------------------------- translate

def test_google_payload_and_overrides(tmp_path):
    assert parse_google('[[["مرحبا ","Hello ",null],["يا صديقي","my friend",null]],null,"en"]') == "مرحبا يا صديقي"
    calls = []
    saved = {}
    t = Translator(backend=lambda text, s, d: calls.append(text) or "آلي", on_overrides_changed=saved.update)
    assert t.translate("Hello there!") == "آلي"
    assert t.translate("hello there") == "آلي" and len(calls) == 1  # cached by normalised key
    t.set_override("Hello there", "هلا والله")
    assert t.translate("HELLO, there") == "هلا والله"
    assert saved == {"hello there": "هلا والله"}


def test_game_rect():
    assert capture.game_rect(1920, 1080) == (0, 0, 1920, 1080)
    assert capture.game_rect(1920, 1200) == (0, 60, 1920, 1080)   # letterbox
    assert capture.game_rect(2000, 1000) == (111, 0, 1778, 1000)  # pillarbox


# ---------------------------------------------------------------- fake TV

class FakeTv:
    def __init__(self):
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen()
        self.port = self.srv.getsockname()[1]
        self.msgs = []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(c,), daemon=True).start()

    def _client(self, c):
        f = c.makefile("r", encoding="utf-8")
        for line in f:
            m = json.loads(line)
            self.msgs.append(m)
            if m["t"] == "hello":
                c.sendall(b'{"t":"welcome","name":"Test TV","overlay":true}\n')
            elif m["t"] == "ping":
                c.sendall(b'{"t":"pong","overlay":true}\n')

    def types(self):
        return [m["t"] for m in self.msgs]


def test_tvlink_handshake_and_send():
    tv = FakeTv()
    link = TvLink("pc")
    link.set_target("127.0.0.1", tv.port)
    assert link.send({"t": "show", "text": "مرحبا", "rect": None})
    time.sleep(0.2)
    assert link.connected and link.tv_name == "Test TV"
    assert tv.types()[:2] == ["hello", "show"]
    assert tv.msgs[1]["text"] == "مرحبا"
    link.close()


# ---------------------------------------------------------------- engine end to end (fake OCR + capture)

def test_engine_flow(tmp_path, monkeypatch):
    tv = FakeTv()
    link = TvLink("pc")
    link.set_target("127.0.0.1", tv.port)
    cfg = Config(tmp_path / "c.json")
    cfg.update({"region": [0.0, 0.5, 1.0, 0.5], "interval": 0.15})

    frame = Image.new("RGB", (1280, 720))
    monkeypatch.setattr(capture, "find_window", lambda title: 1)
    monkeypatch.setattr(capture, "is_minimized", lambda h: False)
    monkeypatch.setattr(capture, "capture_window", lambda h: frame)

    script = {"lines": [Line("Get in the car, now!", Box(500, 250, 780, 290))]}
    monkeypatch.setattr(capture.VideoArea, "update", lambda self, img: (0, 0, img.width, img.height))

    class FakeOcr:
        def read(self, img):
            assert img.size == (1280, 360)  # bottom half of the game
            return script["lines"]

    tr = Translator(backend=lambda text, s, d: "اركب السيارة، الحين!")
    eng = Engine(cfg, link, tr, lambda lang: FakeOcr())
    eng.start()
    deadline = time.time() + 5
    while "show" not in tv.types() and time.time() < deadline:
        time.sleep(0.05)
    shows = [m for m in tv.msgs if m["t"] == "show"]
    assert shows and shows[0]["items"][0]["lines"][0]["t"] == "اركب السيارة، الحين!"
    x, y, w, h = shows[0]["items"][0]["rect"]
    assert abs(x - 500 / 1280) < 0.01 and abs(y - (360 + 250) / 720) < 0.01
    assert abs(w - 280 / 1280) < 0.01 and abs(h - 40 / 720) < 0.01
    assert eng.snapshot()["history"][0]["ar"] == "اركب السيارة، الحين!"

    # the subtitle disappears -> TV is told to clear
    script["lines"] = []
    deadline = time.time() + 5
    while "clear" not in tv.types() and time.time() < deadline:
        time.sleep(0.05)
    assert "clear" in tv.types()

    # user correction is used and pushed
    item = eng.snapshot()["history"][0]
    assert eng.edit(item["id"], "اركب السيارة بسرعة!")
    assert tr.translate("Get in the car, now!") == "اركب السيارة بسرعة!"
    assert eng.snapshot()["history"][0]["ar"] == "اركب السيارة بسرعة!"
    eng.stop()
    link.close()


# ---------------------------------------------------------------- speakers, stacking, calibration

def test_speakers_and_multiple_blocks():
    from tarjem.extract import extract_all, split_speaker
    assert split_speaker("JASON: Stop it, Lucia!") == ("JASON", "Stop it, Lucia!")
    assert split_speaker("Mr. Hale: Sit down.") == ("Mr. Hale", "Sit down.")
    assert split_speaker("It's 10:30 already") == (None, "It's 10:30 already")
    assert split_speaker("we need: guns") == (None, "we need: guns")
    lines = [
        Line("Lucia: Where were you last", Box(420, 520, 860, 550)),
        Line("night?", Box(600, 556, 680, 586)),
        Line("Jason: Working.", Box(520, 592, 760, 622)),
        Line("Cal: You two again?", Box(480, 700, 800, 730)),   # far below: separate block
    ]
    subs = extract_all(lines, 1280, 720)
    assert len(subs) == 2
    assert subs[0].utterances == [("Lucia", "Where were you last night?"), ("Jason", "Working.")]
    assert subs[1].utterances == [("Cal", "You two again?")]


def test_engine_sends_speakers(tmp_path, monkeypatch):
    tv = FakeTv()
    link = TvLink("pc")
    link.set_target("127.0.0.1", tv.port)
    cfg = Config(tmp_path / "c.json")
    cfg.update({"region": [0.0, 0.5, 1.0, 0.5], "interval": 0.15, "calib": {"dy": 0.02}})
    frame = Image.new("RGB", (1280, 720))
    monkeypatch.setattr(capture, "find_window", lambda title: 1)
    monkeypatch.setattr(capture, "is_minimized", lambda h: False)
    monkeypatch.setattr(capture, "capture_window", lambda h: frame)
    monkeypatch.setattr(capture.VideoArea, "update", lambda self, img: (0, 0, img.width, img.height))

    class FakeOcr:
        def read(self, img):
            return [Line("JASON: Stop it, Lucia.", Box(450, 250, 830, 290))]

    names = {"JASON": "جيسون", "Stop it, Lucia.": "توقفي يا لوسيا."}
    eng = Engine(cfg, link, Translator(backend=lambda t, s, d: names[t]), lambda lang: FakeOcr())
    eng.start()
    deadline = time.time() + 5
    while "show" not in tv.types() and time.time() < deadline:
        time.sleep(0.05)
    eng.stop()
    item = [m for m in tv.msgs if m["t"] == "show"][0]["items"][0]
    assert item["lines"] == [{"s": "جيسون", "t": "توقفي يا لوسيا."}]
    assert abs(item["rect"][1] - ((360 + 250) / 720 + 0.02)) < 0.002   # calibration applied
    link.close()


def test_calibration_and_video_area():
    from tarjem.config import apply_calib
    assert apply_calib([0.25, 0.8, 0.5, 0.1], {"dx": 0, "dy": 0, "zoom": 1}) == [0.25, 0.8, 0.5, 0.1]
    assert apply_calib([0.25, 0.8, 0.5, 0.1], {"dx": 0, "dy": 0, "zoom": 1.1}) == [0.225, 0.83, 0.55, 0.11]
    # A 16:9 picture inside a taller window with a toolbar strip: learned from the bright area.
    img = Image.new("RGB", (1280, 800))
    img.paste((90, 120, 60), (0, 50, 1280, 770))
    va = capture.VideoArea()
    x, y, w, h = va.update(img)
    assert abs(y - 50) <= 8 and abs(h - 720) <= 10 and w >= 1270
    # A dark frame alone falls back to the assumed letterbox.
    assert capture.VideoArea().update(Image.new("RGB", (1280, 800))) == capture.game_rect(1280, 800)
