"""Connection to the Tarjem TV app: UDP discovery + TCP JSON lines, with auto-reconnect."""
from __future__ import annotations

import json
import socket
import threading
import time

SERVER_PORT = 47800
DISCOVERY_PORT = 47801
DISCOVERY_REQUEST = b"TARJEM_DISCOVER"


def _broadcast_addresses() -> list[str]:
    addrs = {"255.255.255.255"}
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                parts = ip.split(".")
                addrs.add(".".join(parts[:3] + ["255"]))
    except OSError:
        pass
    return sorted(addrs)


def discover(timeout: float = 2.0) -> list[dict]:
    """Ask every Tarjem TV on the network to answer. Returns [{ip, name, port, overlay}]."""
    found: dict[str, dict] = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.3)
    try:
        s.bind(("", 0))
        end = time.time() + timeout
        next_send = 0.0
        while time.time() < end:
            if time.time() >= next_send:
                for b in _broadcast_addresses():
                    try:
                        s.sendto(DISCOVERY_REQUEST, (b, DISCOVERY_PORT))
                    except OSError:
                        pass
                next_send = time.time() + 0.6
            try:
                data, (ip, _) = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                info = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            if info.get("t") == "tv":
                info["ip"] = ip
                found[ip] = info
    finally:
        s.close()
    return list(found.values())


class TvLink:
    """Keeps one TCP connection to the TV open; send() never blocks the caller for long."""

    def __init__(self, client_name: str = "laptop"):
        self.client_name = client_name
        self.host: str | None = None
        self.port = SERVER_PORT
        self.connected = False
        self.tv_name: str | None = None
        self.tv_overlay: bool | None = None
        self.tv_version: int | None = None
        self.last_error: str | None = None
        self._sock: socket.socket | None = None
        self._lock = threading.RLock()  # re-entrant: on_connect may call send()
        self._stop = threading.Event()
        self._on_connect = None
        threading.Thread(target=self._keepalive, name="tv-keepalive", daemon=True).start()

    def set_target(self, host: str | None, port: int = SERVER_PORT, on_connect=None):
        with self._lock:
            self.host, self.port = (host or None), port
            self._on_connect = on_connect
            self._close_locked()

    def send(self, msg: dict) -> bool:
        line = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:
            if self._sock is None and not self._connect_locked():
                return False
            try:
                self._sock.sendall(line)
                return True
            except OSError as e:
                self.last_error = str(e)
                self._close_locked()
                return False

    def close(self):
        self._stop.set()
        with self._lock:
            self._close_locked()

    # -- internals -------------------------------------------------------------

    def _connect_locked(self) -> bool:
        if not self.host:
            return False
        try:
            s = socket.create_connection((self.host, self.port), timeout=2.5)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.settimeout(2.5)
            s.sendall((json.dumps({"t": "hello", "name": self.client_name}, ensure_ascii=False) + "\n").encode())
            reply = self._read_line(s)
            info = json.loads(reply) if reply else {}
            self.tv_name = info.get("name")
            self.tv_overlay = info.get("overlay")
            self.tv_version = info.get("version")
            s.settimeout(None)
            self._sock = s
            self.connected = True
            self.last_error = None
            threading.Thread(target=self._drain, args=(s,), daemon=True).start()
            if self._on_connect:
                try:
                    self._on_connect()
                except Exception:  # noqa: BLE001 - callback must not break the link
                    pass
            return True
        except (OSError, ValueError) as e:
            self.last_error = str(e)
            self.connected = False
            return False

    @staticmethod
    def _read_line(s: socket.socket) -> str:
        buf = b""
        while not buf.endswith(b"\n") and len(buf) < 65536:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        return buf.decode("utf-8", "replace").strip()

    def _drain(self, s: socket.socket):
        """Read replies (pong/style_ok) so the TV's send buffer never fills; notice disconnects."""
        try:
            f = s.makefile("r", encoding="utf-8")
            for line in f:
                try:
                    info = json.loads(line)
                except ValueError:
                    continue
                if "overlay" in info:
                    self.tv_overlay = info["overlay"]
                if "version" in info:
                    self.tv_version = info["version"]
        except OSError:
            pass
        with self._lock:
            if self._sock is s:
                self._close_locked()

    def _close_locked(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self.connected = False

    def _keepalive(self):
        while not self._stop.wait(3.0):
            if self.host:
                self.send({"t": "ping"})
