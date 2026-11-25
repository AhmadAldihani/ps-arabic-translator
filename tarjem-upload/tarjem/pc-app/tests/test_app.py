import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from tarjem import app as appmod
from tarjem import config as cfgmod


def test_http_api(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(cfgmod, "data_dir", lambda: tmp_path)
    a = appmod.App(ocr_factory=lambda lang: None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), appmod.make_handler(a))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    html = urllib.request.urlopen(base + "/").read().decode()
    assert "ترجم" in html and "/api/state" in html

    st = json.loads(urllib.request.urlopen(base + "/api/state").read())
    assert st["running"] is False and st["config"]["style"]["size"] == 34

    req = urllib.request.Request(base + "/api/config", data=json.dumps({"style": {"size": 44}, "region": [0.2, 0.6, 0.6, 0.3]}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    assert json.loads(urllib.request.urlopen(req).read())["ok"]
    st = json.loads(urllib.request.urlopen(base + "/api/state").read())
    assert st["config"]["style"]["size"] == 44 and st["config"]["region"] == [0.2, 0.6, 0.6, 0.3]
    assert json.loads((tmp_path / "config.json").read_text("utf-8"))["style"]["size"] == 44
    srv.shutdown()
