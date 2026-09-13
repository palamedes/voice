#!/usr/bin/env python3
"""
jarvis_ui.py — a small local web page for Jarvis: see the voices, build a panel of
speakers (Orc, Bard, ...) who each say a line on demand, and script left/right,
iMessage-style conversations that Jarvis reads out loud.

  ./jarvis-ui                      serve http://127.0.0.1:8765 and open it
  ./jarvis-ui --port 9000 --no-open

The page talks to this server; this server talks to the Jarvis server (starting it
when you press Start) the same way ./jarvis does. It only listens on 127.0.0.1.
"""
import argparse
import json
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jarvis_daemon as jarvis  # noqa: E402
from index_speak import list_voices  # noqa: E402

PAGE = Path(__file__).resolve().parent.parent / "ui" / "jarvis.html"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the terminal quiet

    def send_json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def allowed(self) -> bool:
        # Only requests addressed to this machine by name: stops a web page from pointing
        # some other hostname at 127.0.0.1 (DNS rebinding) and driving Jarvis.
        return self.headers.get("Host") in self.server.allowed_hosts

    def do_GET(self):
        if not self.allowed():
            return self.send_json({"ok": False, "error": "forbidden"}, 403)
        if self.path in ("/", "/index.html"):
            data = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/api/status":
            status = jarvis.request({"cmd": "ping"}, timeout=2)
            self.send_json({"running": bool(status), **(status or {})})
        elif self.path == "/api/voices":
            self.send_json({"voices": sorted(list_voices())})
        else:
            self.send_json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        # JSON only, and only from this page: another site can't send a JSON POST here
        # without a CORS preflight, which this server never approves.
        if not self.allowed():
            return self.send_json({"ok": False, "error": "forbidden"}, 403)
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.send_json({"ok": False, "error": "JSON only"}, 415)
        origin = self.headers.get("Origin")
        if origin and origin.removeprefix("http://") not in self.server.allowed_hosts:
            return self.send_json({"ok": False, "error": "forbidden"}, 403)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send_json({"ok": False, "error": "bad JSON"}, 400)

        if self.path == "/api/start":
            # The new server takes a moment before it answers pings; don't let a double
            # click launch two copies of an 8 GB model.
            if time.time() - self.server.last_start < 30:
                return self.send_json({"ok": True, "started": False})
            started = jarvis.start_server(body.get("voice"))
            if started:
                self.server.last_start = time.time()
            self.send_json({"ok": True, "started": started})
        elif self.path == "/api/say":
            resp = jarvis.request({"cmd": "say", "text": str(body.get("text", "")),
                                   "voice": body.get("voice") or None,
                                   "my_breaths": bool(body.get("my_breaths"))}, timeout=15)
            self.send_json(resp or {"ok": False, "error": "Jarvis isn't running"})
        elif self.path in ("/api/stop", "/api/quit"):
            cmd = self.path.rsplit("/", 1)[1]
            resp = jarvis.request({"cmd": cmd}, timeout=5)
            if cmd == "quit":
                self.server.last_start = 0.0
            self.send_json(resp or {"ok": False, "error": "Jarvis isn't running"})
        else:
            self.send_json({"ok": False, "error": "not found"}, 404)


def main() -> int:
    ap = argparse.ArgumentParser(description="A local web page for Jarvis.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="Don't open the page in a browser.")
    args = ap.parse_args()

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        print(f"[jarvis-ui] can't use port {args.port} ({e.strerror}); is the page already "
              f"running? Try --port.", file=sys.stderr)
        return 1
    server.allowed_hosts = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
    server.last_start = 0.0
    url = f"http://127.0.0.1:{args.port}/"
    print(f"[jarvis-ui] {url}  (Ctrl+C stops the page; Jarvis keeps running until you shut it down)")
    if not args.no_open:
        webbrowser.open_new_tab(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
