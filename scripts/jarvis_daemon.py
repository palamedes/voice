#!/usr/bin/env python3
"""
jarvis_daemon.py — Jarvis: a warm Breeze TTS 2 server that speaks in a cloned voice.

./speak and ./say load Breeze from scratch every time (~25 s before the first word).
This server loads it once, warms up fast mode, and stays resident until you quit it.
After that each line starts playing a second or two after you send it, streaming
sentence by sentence: the next sentence renders while the current one plays.

  ./jarvis                   start the server; returns once Breeze is ready
  ./jarvis "Good evening."   speak (starts the server first if it isn't up)
  ./jarvis --art-bell        switch voice; it sticks for later lines
  ./jarvis --stop | --status | --quit

Runs in breeze-tts/.venv. All GPU work happens on one worker thread; the socket
threads only queue requests. A new line interrupts whatever is playing.
"""
import argparse
import json
import os
import queue
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SOCK_PATH = os.environ.get("JARVIS_SOCK", "/tmp/jarvis.sock")
LOG_PATH = os.environ.get("JARVIS_LOG", "/tmp/jarvis.log")
DEFAULT_VOICE = "presenter"
# Speech level (int16 dB scale, as index_speak.speech_level_db measures it) that
# every voice is brought to — about where a loudness-normalized ./speak render sits.
TARGET_LEVEL_DB = 74.0


# ---------------------------------------------------------------- wire protocol
# Each message is a 4-byte big-endian length followed by that many bytes of JSON.
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


def wav_stream_header(sample_rate: int) -> bytes:
    """WAV header with unknown (max) length, so ffplay starts playing immediately."""
    return (
        b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data" + struct.pack("<I", 0xFFFFFFFF)
    )


class Job:
    """One unit of GPU work; `done` is set once it's finished (for a line: once
    playback has ended), `cancel` stops a line between sentences."""

    def __init__(self, run, *args):
        self.run, self.args = run, args
        self.done = threading.Event()
        self.cancel = threading.Event()


# ---------------------------------------------------------------------- server
class Jarvis:
    def __init__(self, voice: str):
        self.voice = voice          # sticky voice for lines that don't name one
        self.jobs: queue.Queue[Job] = queue.Queue()
        self.ready = threading.Event()
        self.error: str | None = None
        self.current: Job | None = None
        self.player: subprocess.Popen | None = None
        self.refs = {}              # voice -> (reference clip, its transcript)
        self.levels = {}            # voice -> speech levels of its recent lines
        self.render = self.sr = None

    # -- GPU thread (the only thread that touches the model) -------------------
    def gpu_loop(self):
        try:
            from index_speak import load_breeze
            t0 = time.time()
            self.render, self.sr = load_breeze(fast=True)
            self.ref_for(self.voice)
            print(f"[jarvis] ready in {time.time() - t0:.1f}s (voice: {self.voice})", flush=True)
        except Exception as e:
            self.error = f"Breeze failed to load: {e}"
            print(f"[jarvis] {self.error}", flush=True)
            return
        finally:
            self.ready.set()
        while True:
            job = self.jobs.get()
            if job.cancel.is_set():
                job.done.set()
                continue
            self.current = job
            try:
                job.run(self, job, *job.args)
            except Exception as e:
                print(f"[jarvis] job failed: {e}", flush=True)
                job.done.set()

    def ref_for(self, voice: str):
        """Reference clip + transcript for a voice, prepared once (transcribed the first time)."""
        if voice not in self.refs:
            from index_speak import MAX_REF_SECS, list_voices, ref_transcript, trim_ref
            clip = list_voices()[voice]
            ref = trim_ref(clip, 0, MAX_REF_SECS)
            self.refs[voice] = (ref, ref_transcript(ref, clip.with_suffix(".txt")))
        return self.refs[voice]

    def level(self, voice: str, speech):
        """Bring a voice to TARGET_LEVEL_DB using the median of its recent lines, so
        reference clips of different loudness match, while one quiet (whispers)
        line still stays quiet."""
        import numpy as np
        from index_speak import speech_level_db
        if not speech.any():
            return speech
        recent = self.levels.setdefault(voice, [])
        recent.append(speech_level_db([speech], self.sr))
        del recent[:-8]
        gain = 10 ** ((TARGET_LEVEL_DB - float(np.median(recent))) / 20)
        gain = min(gain, 32000 / int(np.abs(speech.astype(np.int32)).max()))  # never clip
        return (speech * gain).astype(np.int16)

    def prepare(self, job: Job, voice: str):
        self.ref_for(voice)
        job.done.set()

    def speak(self, job: Job, text: str, auto: bool):
        from audio_common import pacing_plan
        from index_speak import list_voices, tighten_pauses, trim_edges
        plan = pacing_plan(text, auto=auto, voices=set(list_voices()))
        player = subprocess.Popen(["ffplay", "-autoexit", "-nodisp", "-loglevel", "error", "-i", "-"],
                                  stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        self.player = player
        t0, first = time.time(), True
        try:
            player.stdin.write(wav_stream_header(self.sr))
            for chunk, pause_ms, voice in plan:
                if job.cancel.is_set():
                    break
                pcm = b""
                if chunk:
                    voice = voice or self.voice
                    speech = trim_edges(self.render(chunk, *self.ref_for(voice)), self.sr)
                    if not auto:
                        speech = tighten_pauses(speech, self.sr)
                    pcm = self.level(voice, speech).tobytes()
                    if first:
                        print(f"[jarvis] first audio in {time.time() - t0:.2f}s", flush=True)
                        first = False
                if job.cancel.is_set():
                    break
                player.stdin.write(pcm + bytes(2 * (self.sr * pause_ms // 1000)))
            player.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        # Let it play out on the side, so the GPU thread can take the next job.
        threading.Thread(target=lambda: (player.wait(), job.done.set()), daemon=True).start()

    # -- requests ---------------------------------------------------------------
    def interrupt(self):
        """Stop the current line and drop any that haven't started."""
        for job in [self.current, *list(self.jobs.queue)]:
            if job and job.run == Jarvis.speak:
                job.cancel.set()
        player = self.player
        if player and player.poll() is None:
            try:
                player.kill()
            except OSError:
                pass

    def handle(self, conn: socket.socket):
        req = recv_json(conn)
        if not req:
            return
        cmd = req.get("cmd")
        if cmd == "ping":
            send_json(conn, {"ok": True, "ready": self.ready.is_set(), "voice": self.voice,
                             "error": self.error})
        elif cmd == "stop":
            self.interrupt()
            send_json(conn, {"ok": True})
        elif cmd == "quit":
            send_json(conn, {"ok": True})
            self.interrupt()
            os._exit(0)
        elif cmd in ("say", "voice"):
            if not self.ready.is_set() or self.error:
                send_json(conn, {"ok": False, "error": self.error or "still loading"})
                return
            voice = req.get("voice")
            if voice:
                from index_speak import list_voices
                if voice not in list_voices():
                    send_json(conn, {"ok": False, "error": f"unknown voice {voice!r}"})
                    return
                self.voice = voice
            if cmd == "voice":
                self.jobs.put(Job(Jarvis.prepare, self.voice))
                send_json(conn, {"ok": True, "voice": self.voice})
                return
            text = (req.get("text") or "").strip()
            if not text:
                send_json(conn, {"ok": False, "error": "empty text"})
                return
            self.interrupt()
            job = Job(Jarvis.speak, text, not req.get("my_breaths"))
            self.jobs.put(job)
            if req.get("wait"):
                job.done.wait()
            send_json(conn, {"ok": True, "voice": self.voice})
        else:
            send_json(conn, {"ok": False, "error": f"unknown cmd {cmd!r}"})

    def serve(self):
        path = Path(SOCK_PATH)
        if path.exists():
            if request({"cmd": "ping"}, timeout=2):
                print("[jarvis] already running; not starting a second server", flush=True)
                return
            path.unlink()  # stale socket from a dead server
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCK_PATH)
        srv.listen(8)
        print("[jarvis] loading Breeze TTS 2...", flush=True)
        threading.Thread(target=self.gpu_loop, daemon=True).start()
        print(f"[jarvis] listening on {SOCK_PATH}", flush=True)
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn: socket.socket):
        try:
            self.handle(conn)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print(f"[jarvis] request failed: {e}", flush=True)
        finally:
            conn.close()


# ---------------------------------------------------------------------- client
def request(obj: dict, timeout: float | None = 10.0) -> dict | None:
    """Send one request to the server; None if it isn't reachable."""
    try:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(timeout)
        conn.connect(SOCK_PATH)
        send_json(conn, obj)
        resp = recv_json(conn)
        conn.close()
        return resp
    except (OSError, ValueError):
        return None


def start_server(voice: str | None = None) -> bool:
    """Start the server in the background unless one already answers. True if it started one."""
    if request({"cmd": "ping"}, timeout=2):
        return False
    with open(LOG_PATH, "ab") as log:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve",
                          "--voice", voice or DEFAULT_VOICE],
                         stdout=log, stderr=log, start_new_session=True)
    return True


def ensure_running(voice: str | None) -> dict | None:
    """Ping the server, starting it if needed; return its status once Breeze is ready."""
    if start_server(voice):
        print("[jarvis] starting the server (loading Breeze, ~25 s)...", file=sys.stderr)
    deadline = time.time() + 300   # first use of a voice also transcribes its clip
    while time.time() < deadline:
        status = request({"cmd": "ping"}, timeout=2)
        if status and status.get("error"):
            print(f"[jarvis] {status['error']} (see {LOG_PATH})", file=sys.stderr)
            return None
        if status and status.get("ready"):
            return status
        time.sleep(0.5)
    print(f"[jarvis] the server didn't come up; see {LOG_PATH}", file=sys.stderr)
    return None


def main() -> int:
    from index_speak import list_voices
    voices = list_voices()
    # Any voice name works as a bare flag: --art-bell, --presenter, ...
    argv = []
    for a in sys.argv[1:]:
        argv += ["--voice", a[2:]] if a.startswith("--") and a[2:] in voices else [a]

    ap = argparse.ArgumentParser(description="Jarvis: a warm Breeze server that speaks in a cloned voice.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--serve", action="store_true", help="Run the server in the foreground.")
    mode.add_argument("--stop", action="store_true", help="Stop talking.")
    mode.add_argument("--quit", action="store_true", help="Shut the server down (frees the GPU memory).")
    mode.add_argument("--status", action="store_true", help="Is it up, and in which voice?")
    mode.add_argument("--list-voices", action="store_true", help="List voices and exit.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--text", type=str)
    src.add_argument("--file", type=Path)
    ap.add_argument("words", nargs="*", help="Text to say (alternative to --text).")
    ap.add_argument("--voice", help="Voice to use from now on (see --list-voices); sticks for later lines.")
    ap.add_argument("--my-breaths", action="store_true",
                    help="Pause only at your ,,, / [breath] / [pause] marks and line breaks.")
    ap.add_argument("--wait", action="store_true", help="Block until it finishes speaking.")
    args = ap.parse_intermixed_args(argv)

    if args.voice and args.voice not in voices:
        ap.error(f"unknown voice {args.voice!r} (see --list-voices)")
    if args.serve:
        Jarvis(args.voice or DEFAULT_VOICE).serve()
        return 0
    if args.list_voices:
        print("Available voices:")
        for name, path in voices.items():
            print(f"  {name}")
        return 0
    if args.status:
        status = request({"cmd": "ping"}, timeout=2)
        if not status:
            print("jarvis: not running")
            return 1
        print(f"jarvis: {'ready' if status.get('ready') else 'loading'} (voice: {status.get('voice')})")
        return 0
    if args.stop or args.quit:
        if not request({"cmd": "stop" if args.stop else "quit"}, timeout=5):
            print("jarvis: not running", file=sys.stderr)
            return 1
        return 0

    if args.file:
        from audio_common import strip_markdown
        text = strip_markdown(args.file.read_text(encoding="utf-8"))
    else:
        text = args.text if args.text is not None else " ".join(args.words)

    status = ensure_running(args.voice)
    if not status:
        return 1
    if not text.strip():
        # No text: just make sure it's up (and switch voice if one was given).
        if args.voice:
            status = request({"cmd": "voice", "voice": args.voice})
        print(f"[jarvis] ready (voice: {(status or {}).get('voice')})")
        return 0
    resp = request({"cmd": "say", "text": text, "voice": args.voice,
                    "my_breaths": args.my_breaths, "wait": args.wait},
                   timeout=None if args.wait else 15)
    if not resp or not resp.get("ok"):
        print(f"[jarvis] error: {(resp or {}).get('error', 'no response')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
