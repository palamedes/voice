#!/usr/bin/env python3
"""
voice_daemon.py — Jarvis mode: a warm Kokoro-82M daemon for near-instant speech.

Why: fast_speak.py cold-starts Python + torch + the model + phonemizer on every
call (~10-15 s), generates the WHOLE clip, normalizes it, and only then plays.
This daemon loads the model once, stays resident, and streams audio to the
speakers sentence-by-sentence — the first sentence plays while the rest is
still generating. Warm latency to first sound is a fraction of a second.

Server:   kokoro/.venv/bin/python scripts/voice_daemon.py --serve
Client:   kokoro/.venv/bin/python scripts/voice_daemon.py --text "Hello, sir."
          (auto-starts the server on first use; later calls are instant)

A new say request interrupts whatever is currently playing — like talking over
Jarvis. `--stop` interrupts without saying anything new.
"""
import argparse
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fast_speak import VOICES  # curated voice list, shared with /speak-fast

SOCK_PATH = os.environ.get("VOICE_DAEMON_SOCK", "/tmp/voice_daemon.sock")
LOG_PATH = os.environ.get("VOICE_DAEMON_LOG", "/tmp/voice_daemon.log")
SAMPLE_RATE = 24000
DEFAULT_VOICE = "am_adam"
# Split into sentences so the first one can play while the rest generate.
SPLIT_PATTERN = r"(?<=[.!?;:…])\s+|\n+"


# ---------------------------------------------------------------- wire protocol
def send_json(conn: socket.socket, obj: dict):
    data = json.dumps(obj).encode("utf-8")
    conn.sendall(struct.pack("!I", len(data)) + data)


def recv_json(conn: socket.socket) -> dict | None:
    header = _recv_exact(conn, 4)
    if header is None:
        return None
    (length,) = struct.unpack("!I", header)
    data = _recv_exact(conn, length)
    return json.loads(data) if data is not None else None


def _recv_exact(conn: socket.socket, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def wav_stream_header(sample_rate: int = SAMPLE_RATE) -> bytes:
    """WAV header with unknown (max) length, so a player can start immediately."""
    return (
        b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data" + struct.pack("<I", 0xFFFFFFFF)
    )


# ---------------------------------------------------------------------- server
class Server:
    def __init__(self):
        self.pipelines = {}          # lang_code -> KPipeline
        self.cancel = threading.Event()
        self.player: subprocess.Popen | None = None
        self.worker: threading.Thread | None = None
        self.lock = threading.Lock()        # serializes utterances
        self.speak_lock = threading.Lock()  # serializes interrupt-then-start

    def pipeline_for(self, voice: str):
        lang = voice[0]  # 'a' American, 'b' British
        if lang not in self.pipelines:
            from kokoro import KPipeline
            self.pipelines[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
        return self.pipelines[lang]

    def warm_up(self):
        import numpy as np  # noqa: F401  (imported here so --help stays fast)
        t0 = time.time()
        pipe = self.pipeline_for(DEFAULT_VOICE)
        for _ in pipe("Ready.", voice=DEFAULT_VOICE):
            pass
        print(f"[daemon] model warm in {time.time() - t0:.1f}s", flush=True)

    # -- playback -------------------------------------------------------------
    def interrupt(self):
        """Stop the current utterance (if any) and wait for its worker to exit."""
        self.cancel.set()
        player = self.player
        if player and player.poll() is None:
            try:
                player.kill()
            except OSError:
                pass
        worker = self.worker
        if worker and worker.is_alive():
            worker.join(timeout=5)

    def speak(self, text: str, voice: str, speed: float) -> threading.Thread:
        with self.speak_lock:
            self.interrupt()
            self.cancel.clear()
            self.worker = threading.Thread(
                target=self._speak_worker, args=(text, voice, speed), daemon=True)
            self.worker.start()
            return self.worker

    def _speak_worker(self, text: str, voice: str, speed: float):
        import numpy as np
        with self.lock:
            try:
                pipe = self.pipeline_for(voice)
                player = subprocess.Popen(
                    ["ffplay", "-autoexit", "-nodisp", "-loglevel", "error", "-i", "-"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.player = player
                player.stdin.write(wav_stream_header())
                t0, first = time.time(), True
                for _gs, _ps, audio in pipe(text, voice=voice, speed=speed,
                                            split_pattern=SPLIT_PATTERN):
                    if self.cancel.is_set():
                        break
                    if first:
                        print(f"[daemon] first audio in {time.time() - t0:.2f}s", flush=True)
                        first = False
                    samples = np.asarray(audio, dtype=np.float32)
                    peak = np.abs(samples).max() or 1.0
                    if peak > 1.0:
                        samples = samples / peak
                    pcm = (samples * 32767).astype(np.int16).tobytes()
                    try:
                        player.stdin.write(pcm)
                    except BrokenPipeError:
                        break
                try:
                    player.stdin.close()
                    player.wait(timeout=600)
                except (OSError, subprocess.TimeoutExpired):
                    player.kill()
            except Exception as e:
                print(f"[daemon] speak failed: {e}", flush=True)

    # -- request loop ---------------------------------------------------------
    def handle(self, conn: socket.socket):
        req = recv_json(conn)
        if not req:
            return
        cmd = req.get("cmd")
        if cmd == "ping":
            send_json(conn, {"ok": True, "warm": bool(self.pipelines)})
        elif cmd == "stop":
            self.interrupt()
            send_json(conn, {"ok": True})
        elif cmd == "quit":
            send_json(conn, {"ok": True})
            self.interrupt()
            os._exit(0)
        elif cmd == "say":
            text = (req.get("text") or "").strip()
            voice = req.get("voice") or DEFAULT_VOICE
            speed = float(req.get("speed") or 1.0)
            if not text:
                send_json(conn, {"ok": False, "error": "empty text"})
                return
            if voice not in VOICES:
                send_json(conn, {"ok": False, "error": f"unknown voice {voice!r}"})
                return
            worker = self.speak(text, voice, speed)
            if req.get("wait"):
                worker.join()
                send_json(conn, {"ok": True, "done": True})
            else:
                send_json(conn, {"ok": True, "speaking": True})
        else:
            send_json(conn, {"ok": False, "error": f"unknown cmd {cmd!r}"})

    def serve(self):
        path = Path(SOCK_PATH)
        if path.exists():
            path.unlink()  # stale socket from a dead daemon (client pinged first)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCK_PATH)
        srv.listen(4)
        print(f"[daemon] loading Kokoro-82M...", flush=True)
        self.warm_up()
        print(f"[daemon] listening on {SOCK_PATH}", flush=True)
        while True:
            conn, _ = srv.accept()
            # One thread per request, so --stop can get through while a
            # --wait say is still blocking on playback.
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn: socket.socket):
        try:
            self.handle(conn)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client gave up (e.g. a startup ping that timed out mid-load)
        except Exception as e:
            print(f"[daemon] request failed: {e}", flush=True)
        finally:
            conn.close()


# ---------------------------------------------------------------------- client
def request(obj: dict, timeout: float = 10.0) -> dict | None:
    """Send one request to the daemon; None if it isn't reachable."""
    try:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(timeout)
        conn.connect(SOCK_PATH)
        send_json(conn, obj)
        if obj.get("wait"):
            conn.settimeout(None)  # long utterances outlive any fixed timeout
        resp = recv_json(conn)
        conn.close()
        return resp
    except (OSError, json.JSONDecodeError):
        return None


def ensure_daemon() -> bool:
    """Return True once the daemon answers a ping, starting it if needed."""
    if request({"cmd": "ping"}, timeout=2):
        return True
    log = open(LOG_PATH, "ab")
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--serve"],
        stdout=log, stderr=log, start_new_session=True)
    print("[jarvis] starting voice daemon (one-time model load)...", file=sys.stderr)
    deadline = time.time() + 180  # generous: first-ever run downloads weights
    while time.time() < deadline:
        if request({"cmd": "ping"}, timeout=2):
            return True
        time.sleep(0.3)
    print(f"[jarvis] daemon did not come up; see {LOG_PATH}", file=sys.stderr)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Warm Kokoro daemon for near-instant speech.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--serve", action="store_true", help="Run the daemon in the foreground.")
    mode.add_argument("--stop", action="store_true", help="Interrupt current playback.")
    mode.add_argument("--quit", action="store_true", help="Shut the daemon down.")
    mode.add_argument("--status", action="store_true", help="Is the daemon up?")
    mode.add_argument("--list-voices", action="store_true", help="List voices and exit.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--text", type=str)
    src.add_argument("--file", type=Path)
    ap.add_argument("--voice", default=DEFAULT_VOICE, choices=list(VOICES))
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--wait", action="store_true",
                    help="Block until playback finishes (default: return immediately).")
    ap.add_argument("words", nargs="*", help="Text to say (alternative to --text).")
    args = ap.parse_args()

    if args.serve:
        Server().serve()
        return 0
    if args.list_voices:
        print("Available voices:")
        for name, desc in VOICES.items():
            print(f"  {name:12s} {desc}")
        return 0
    if args.status:
        resp = request({"cmd": "ping"}, timeout=2)
        print("daemon: up (model warm)" if resp else "daemon: not running")
        return 0 if resp else 1
    if args.stop or args.quit:
        resp = request({"cmd": "stop" if args.stop else "quit"}, timeout=5)
        if not resp:
            print("daemon: not running", file=sys.stderr)
            return 1
        return 0

    if args.file:
        text = args.file.read_text(encoding="utf-8")
        from audio_common import strip_markdown
        text = strip_markdown(text)
    else:
        text = args.text if args.text is not None else " ".join(args.words)
    if not text.strip():
        ap.error("nothing to say — pass text, --text, or --file")

    if not ensure_daemon():
        return 1
    resp = request({"cmd": "say", "text": text, "voice": args.voice,
                    "speed": args.speed, "wait": args.wait}, timeout=15)
    if not resp or not resp.get("ok"):
        print(f"[jarvis] error: {(resp or {}).get('error', 'no response')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
