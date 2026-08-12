# -*- coding: utf-8 -*-
"""血之游戏 —— 记忆推理抢答，主持人投屏 + 手机同步作答。

只用 Python 标准库（二维码需要可选的 qrcode 包）。
    py server.py            默认 8000 端口
    py server.py 9000       指定端口
"""

import json
import mimetypes
import os
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game import catalog, engine, gen_ai  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")
CONFIG_PATH = os.path.join(BASE, "config.json")

POLL_TIMEOUT = 25.0          # 长轮询最长挂多久
CONFIG = {}


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def load_config():
    global CONFIG
    CONFIG = {"port": 8000, "deepseek_api_key": "",
              "deepseek_model": gen_ai.DEFAULT_MODEL,
              "open_browser": True}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            CONFIG.update(json.load(f))
    except FileNotFoundError:
        pass
    except Exception as e:
        print("!! config.json 读取失败：%s（使用默认配置）" % e)

    # Environment variables take precedence so secrets never need to be
    # committed to a project file.
    if os.environ.get("DEEPSEEK_API_KEY") is not None:
        CONFIG["deepseek_api_key"] = os.environ["DEEPSEEK_API_KEY"].strip()
    if os.environ.get("DEEPSEEK_MODEL"):
        CONFIG["deepseek_model"] = os.environ["DEEPSEEK_MODEL"].strip()
    if os.environ.get("BLOOD_GAME_PORT"):
        try:
            CONFIG["port"] = int(os.environ["BLOOD_GAME_PORT"])
        except ValueError:
            print("!! BLOOD_GAME_PORT 不是有效整数（使用当前端口配置）")
    CONFIG["open_browser"] = _env_bool(
        "BLOOD_GAME_OPEN_BROWSER", CONFIG["open_browser"])
    return CONFIG


def lan_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips or ["127.0.0.1"]


def qr_svg(text, size=300):
    try:
        import qrcode
    except ImportError:
        return None
    try:
        qr = qrcode.QRCode(border=2,
                           error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(text)
        qr.make(fit=True)
        m = qr.get_matrix()
    except Exception:
        return None
    n = len(m)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
             'viewBox="0 0 %d %d" shape-rendering="crispEdges">' % (size, size, n, n),
             '<rect width="%d" height="%d" fill="#fff"/>' % (n, n)]
    for y, row in enumerate(m):
        x = 0
        while x < n:
            if row[x]:
                x2 = x
                while x2 + 1 < n and row[x2 + 1]:
                    x2 += 1
                parts.append('<rect x="%d" y="%d" width="%d" height="1" '
                             'fill="#000"/>' % (x, y, x2 - x + 1))
                x = x2 + 1
            else:
                x += 1
    parts.append("</svg>")
    return "".join(parts)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "XueZhiYouXi"

    def log_message(self, fmt, *args):
        pass

    # ---------------- 基础 ----------------

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body, ctype, code=200, cache=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control",
                         "max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def serve_file(self, rel):
        path = os.path.normpath(os.path.join(WEB, rel.lstrip("/")))
        if not path.startswith(WEB) or not os.path.isfile(path):
            self.send_bytes(b"404", "text/plain; charset=utf-8", 404)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",
                                                  "image/svg+xml"):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            self.send_bytes(f.read(), ctype, cache=False)

    # ---------------- GET ----------------

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p, q = u.path, urllib.parse.parse_qs(u.query)

        if p in ("/", "/index.html"):
            return self.serve_file("index.html")
        if p in ("/host", "/h"):
            return self.serve_file("host.html")
        if p in ("/p", "/play", "/player"):
            return self.serve_file("player.html")
        if p == "/favicon.ico":
            return self.send_bytes(b"", "image/x-icon")

        if p == "/api/games":
            return self.send_json({"games": catalog.public_list()})

        if p == "/api/net":
            port = self.server.server_address[1]
            return self.send_json({
                "ips": lan_ips(), "port": port,
                "join": ["http://%s:%d/p" % (ip, port) for ip in lan_ips()]})

        if p == "/api/qr":
            svg = qr_svg((q.get("t") or [""])[0])
            if not svg:
                return self.send_bytes(b"", "image/svg+xml", 404)
            return self.send_bytes(svg.encode("utf-8"), "image/svg+xml")

        if p == "/api/draw":
            room = engine.get_room((q.get("room") or [""])[0])
            if not room:
                return self.send_json({"error": "no_room"}, 404)
            return self.send_json(
                room.strokes_since((q.get("since") or ["0"])[0]))

        if p == "/api/state":
            return self.api_state(q)

        return self.serve_file(p)

    def api_state(self, q):
        code = (q.get("room") or [""])[0]
        pid = (q.get("pid") or [""])[0] or None
        since = int((q.get("since") or ["0"])[0] or 0)
        hk = (q.get("hk") or [""])[0]

        room = engine.get_room(code)
        if not room:
            return self.send_json({"error": "no_room"}, 404)
        is_host = bool(hk) and hk == room.host_key

        end = time.time() + POLL_TIMEOUT
        while True:
            snap = room.snapshot(pid=pid, is_host=is_host)
            if snap["v"] != since or time.time() >= end:
                return self.send_json(snap)
            engine.wait_change(min(1.0, max(0.05, end - time.time())))

    # ---------------- POST ----------------

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        data = self.read_json()

        if p == "/api/host/create":
            st = engine.default_settings(
                api_key=CONFIG.get("deepseek_api_key", ""),
                model=CONFIG.get("deepseek_model", gen_ai.DEFAULT_MODEL))
            room = engine.create_room(st)
            # 先套用玩法预设，再让页面上填的值覆盖它
            gid = str(data.get("game") or "classic")
            room.game = gid
            room.game_name = catalog.name_of(gid)
            merged = catalog.preset_of(gid)
            merged.update({k: v for k, v in data.items() if k != "game"})
            room.act("settings", merged)
            port = self.server.server_address[1]
            return self.send_json({
                "room": room.code, "hk": room.host_key,
                "join": ["http://%s:%d/p?room=%s" % (ip, port, room.code)
                         for ip in lan_ips()]})

        if p == "/api/host/act":
            room = engine.get_room(data.get("room"))
            if not room:
                return self.send_json({"error": "no_room"}, 404)
            if data.get("hk") != room.host_key:
                return self.send_json({"error": "bad_key"}, 403)
            room.act(data.get("action", ""), data.get("payload") or {})
            return self.send_json({"ok": True})

        if p == "/api/join":
            room = engine.get_room(data.get("room"))
            if not room:
                return self.send_json({"error": "no_room"}, 404)
            pl = room.join(str(data.get("name") or "").strip(),
                           data.get("pid") or None)
            return self.send_json({"ok": True, "pid": pl.pid, "name": pl.name,
                                   "room": room.code})

        if p == "/api/submit":
            room = engine.get_room(data.get("room"))
            if not room:
                return self.send_json({"error": "no_room"}, 404)
            room.submit(data.get("pid"), data.get("payload") or {})
            return self.send_json({"ok": True})

        if p == "/api/answer":
            room = engine.get_room(data.get("room"))
            if not room:
                return self.send_json({"error": "no_room"}, 404)
            room.answer(data.get("pid"), data.get("q"), data.get("choice"))
            return self.send_json({"ok": True})

        return self.send_json({"error": "not_found"}, 404)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    load_config()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(CONFIG.get("port", 8000))
    engine.start_ticker()

    httpd = None
    for tryport in range(port, port + 20):
        try:
            httpd = Server(("0.0.0.0", tryport), Handler)
            port = tryport
            break
        except OSError:
            continue
    if not httpd:
        print("端口 %d~%d 都被占用了。" % (port, port + 19))
        return

    ips = lan_ips()
    line = "=" * 52
    print(line)
    print("  血之游戏  已启动")
    print(line)
    print("  主持人（投屏用这个）: http://localhost:%d/host" % port)
    for ip in ips:
        print("  玩家（手机扫码/输入）: http://%s:%d/p" % (ip, port))
    print(line)
    print("  手机要和这台电脑在同一个 Wi-Fi 下。")
    print("  关闭窗口即可停止服务。")
    print(line)
    sys.stdout.flush()

    if CONFIG.get("open_browser", True):
        try:
            import webbrowser
            threading.Timer(
                0.6, lambda: webbrowser.open(
                    "http://localhost:%d/host" % port)).start()
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
