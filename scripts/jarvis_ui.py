#!/usr/bin/env python3
"""
jarvis_ui.py — a small local web page for Jarvis: see the voices, build a panel of
speakers (Orc, Bard, ...) who each say a line on demand, and script left/right,
iMessage-style conversations that Jarvis reads out loud.

  ./jarvis-ui                      start Jarvis, serve http://127.0.0.1:8765 and open it
  ./jarvis-ui --port 9000 --no-open --no-start --keep-jarvis

The page talks to this server; this server talks to the Jarvis server the same way
./jarvis does. Shut down on the page, or Ctrl+C here, stops both (--keep-jarvis
leaves Jarvis running). It only listens on 127.0.0.1.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jarvis_daemon as jarvis  # noqa: E402
from audio_common import strip_markdown  # noqa: E402
from index_speak import list_voices  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "ui" / "jarvis.html"
# Saved conversations: one JSON file each, so scenes can also be prepared in an editor.
CONVERSATIONS = ROOT / "conversations"
# Render out writes here, like ./speak does (JARVIS_OUTPUT moves it, which tests use).
OUTPUT = Path(os.environ.get("JARVIS_OUTPUT") or ROOT / "output")
# Save post writes the article here as Markdown (JARVIS_POSTS moves it).
POSTS = Path(os.environ.get("JARVIS_POSTS") or ROOT / "posts")
# The articles open on the page: one JSON each, saved as you type (JARVIS_ARTICLES moves it).
ARTICLES = Path(os.environ.get("JARVIS_ARTICLES") or ROOT / "articles")


def slug(name: str) -> str:
    """File name for a conversation's display name ("Rusty Tankard" -> rusty-tankard)."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80] or "untitled"


def free_name(path: Path) -> Path:
    """path, or path-2, path-3, ... so a render never writes over an earlier one."""
    stem, n = path.stem, 2
    while path.exists():
        path = path.with_name(f"{stem}-{n}{path.suffix}")
        n += 1
    return path


def safe_path(folder: Path, name: str, suffix: str) -> Path | None:
    """folder/<name><suffix>, or None if the name could point outside that folder."""
    path = folder / f"{name}{suffix}"
    if not name or "/" in name or "\\" in name or name.startswith(".") or path.parent != folder:
        return None
    return path


def conversation_path(cid: str) -> Path | None:
    return safe_path(CONVERSATIONS, cid, ".json")


def article_path(aid: str) -> Path | None:
    return safe_path(ARTICLES, aid, ".json")


def clean_article(name: str, doc: dict) -> dict:
    """Keep only the fields the page uses, with sane types (files may be hand-edited)."""
    paras = []
    for para in doc.get("paras") or []:
        if not isinstance(para, dict) or not str(para.get("text", "")).strip():
            continue
        kept = {"text": str(para["text"]).strip()}
        if para.get("voice"):
            kept["voice"] = str(para["voice"])
        paras.append(kept)
    rate = doc.get("rate")
    return {"name": name, "voice": str(doc.get("voice") or ""),
            "myBreaths": bool(doc.get("myBreaths")),
            "rate": min(max(float(rate), 0.5), 2.0) if isinstance(rate, (int, float)) else 1.0,
            # The post in posts/ this article writes, and the name it was written under.
            "postId": str(doc.get("postId") or ""),
            "postName": str(doc.get("postName") or ""),
            "paras": paras}


def clean_conversation(name: str, conv: dict) -> dict:
    """Keep only the fields the page uses, with sane types (files may be hand-edited)."""
    lines = []
    for line in conv.get("lines") or []:
        if not isinstance(line, dict):
            continue
        side, text = line.get("side"), str(line.get("text", "")).strip()
        if side in ("left", "right", "guest") and text:
            entry = {"side": side, "text": text}
            if side == "guest":
                entry["voice"] = str(line.get("voice") or "")
            lines.append(entry)
    cast = [{"voice": str(m["voice"]), "label": str(m.get("label") or m["voice"])}
            for m in conv.get("cast") or [] if isinstance(m, dict) and m.get("voice")]
    return {"name": name, "left": str(conv.get("left") or ""), "right": str(conv.get("right") or ""),
            "cast": cast, "lines": lines}


VOICE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")


def git(*args, **run):
    """Run git in the project (never through a shell)."""
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, **run)


def tracked(paths: list[Path]) -> list[Path]:
    """Which of these files git has."""
    if not paths:
        return []
    known = set(git("ls-files", "--", *[str(p) for p in paths]).stdout.splitlines())
    return [p for p in paths if str(p.relative_to(ROOT)) in known]


def loose_voices() -> list[str]:
    """Voices that aren't safely in the repo: a clip or transcript that git doesn't have,
    or has but that's changed since. Named by file, as list_voices names them."""
    names = set()
    for args in (("ls-files", "--others", "--exclude-standard"), ("ls-files", "--modified")):
        for line in git(*args, "--", "voice_samples").stdout.splitlines():
            names.add(Path(line).stem)
    return sorted(names & set(list_voices()))


def voice_files(names: list[str]) -> list[Path]:
    """Every file that makes up these voices: the clip, and the transcript beside it."""
    known = list_voices()
    files = []
    for name in names:
        clip = known[name]
        files += [p for p in (clip, clip.with_suffix(".txt")) if p.exists()]
    return files


def named(names: list[str]) -> str:
    return f"the {names[0]} voice" if len(names) == 1 else f"{len(names)} voices: {', '.join(names)}"


def commit_voices(names: list[str]) -> tuple[bool, str]:
    """Put these clips and transcripts into the repo (it never pushes)."""
    files = [str(p) for p in voice_files(names)]
    add = git("add", "--", *files)
    if add.returncode:
        return False, add.stderr.strip()[:200]
    done = git("commit", "-m", f"Add {named(names)}", "--", *files)
    if done.returncode:
        return False, (done.stdout + done.stderr).strip()[:200]
    return True, git("log", "--oneline", "-1").stdout.strip()


def untrack_voices(names: list[str]) -> tuple[bool, str]:
    """Stop tracking these clips, leaving the files where they are. The removal has to be
    committed from the index (the files stay on disk, so committing them by name would
    only put them back), so it goes no further than a tidy index allows."""
    files = [str(p) for p in tracked(voice_files(names))]
    if not files:
        return False, "git hasn't got those clips anyway"
    if git("diff", "--cached", "--name-only").stdout.strip():
        return False, "something else is already staged here — commit or unstage it first"
    out = git("rm", "--cached", "-q", "--", *files)
    if out.returncode:
        return False, out.stderr.strip()[:200]
    done = git("commit", "-m", f"Take {named(names)} out of the repo")
    if done.returncode:
        git("reset", "-q", "--", *files)        # put the index back as it was
        return False, (done.stdout + done.stderr).strip()[:200]
    return True, git("log", "--oneline", "-1").stdout.strip()


def delete_voices(names: list[str]) -> tuple[bool, str]:
    """Delete these clips and transcripts; if git had them, commit their removal too."""
    files = voice_files(names)
    have = [str(p) for p in tracked(files)]
    if have:
        out = git("rm", "-q", "--", *have)
        if out.returncode:
            return False, out.stderr.strip()[:200]
        done = git("commit", "-m", f"Delete {named(names)}", "--", *have)
        if done.returncode:
            return False, (done.stdout + done.stderr).strip()[:200]
    for path in files:
        path.unlink(missing_ok=True)      # whatever git wasn't keeping
    return True, f"deleted {', '.join(names)}"


def rename_voice(old: str, new: str) -> tuple[bool, str]:
    """Rename a voice: its clip, its transcript, and the name in any saved article or
    conversation (including [voice] switches in their text)."""
    known = list_voices()
    if not VOICE_NAME.match(new):
        return False, "a voice name takes lowercase letters, numbers and dashes"
    if new in known:
        return False, f"there's already a voice called {new}"
    moved = []
    for path in voice_files([old]):
        to = path.with_name(new + path.suffix)
        if tracked([path]):
            out = git("mv", "--", str(path), str(to))
            if out.returncode:
                return False, out.stderr.strip()[:200]
        else:
            path.rename(to)
        moved.append(to)
    if tracked(moved):
        git("commit", "-m", f"Rename the {old} voice to {new}", "--",
            *[str(p) for p in moved], *[str(p.with_name(old + p.suffix)) for p in moved])
    swapped = swap_voice(old, new)
    return True, f"renamed to {new}" + (f", and in {swapped} saved file{'s' * (swapped != 1)}" if swapped else "")


def _swap(node, old: str, new: str):
    if isinstance(node, dict):
        return {k: (new if k in ("voice", "left", "right") and v == old else _swap(v, old, new))
                for k, v in node.items()}
    if isinstance(node, list):
        return [_swap(v, old, new) for v in node]
    if isinstance(node, str):
        return node.replace(f"[{old}]", f"[{new}]")
    return node


def swap_voice(old: str, new: str) -> int:
    """Point saved articles and conversations at a voice's new name. Returns how many changed."""
    changed = 0
    for folder in (CONVERSATIONS, ARTICLES):
        for f in folder.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            fixed = _swap(data, old, new)
            if fixed != data:
                f.write_text(json.dumps(fixed, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                changed += 1
    return changed


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

    def send_download(self, data: bytes, filename: str):
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
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
            known = sorted(list_voices())
            loose = loose_voices()
            in_repo = [v for v in known if tracked(voice_files([v]))]
            self.send_json({"voices": known, "loose": loose, "tracked": in_repo})
        elif self.path == "/api/conversations":
            found = []
            for f in CONVERSATIONS.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue    # a half-written or hand-broken file; load reports it
                found.append({"id": f.stem, "name": str(data.get("name") or f.stem),
                              "lines": len(data.get("lines") or [])})
            found.sort(key=lambda c: c["name"].casefold())
            self.send_json({"conversations": found})
        elif self.path == "/api/articles":
            found = []
            for f in ARTICLES.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue    # a half-written or hand-broken file; load reports it
                found.append({"id": f.stem, "name": str(data.get("name") or f.stem),
                              "paragraphs": len(data.get("paras") or [])})
            found.sort(key=lambda a: a["name"].casefold())
            self.send_json({"articles": found})
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
            # Lines from the page wait their turn instead of cutting off what's playing;
            # only Stop talking interrupts. The reply's id can be followed with /api/wait.
            text = str(body.get("text", ""))
            if body.get("markdown"):
                text = strip_markdown(text)
                if not text:
                    return self.send_json({"ok": True, "skipped": True})   # only Markdown syntax
            msg = {"cmd": "say", "text": text, "voice": body.get("voice") or None,
                   "my_breaths": bool(body.get("my_breaths")), "queue": bool(body.get("queue", True))}
            if isinstance(body.get("gap_ms"), int):
                msg["gap_ms"] = body["gap_ms"]   # the pause before it, if something is still playing
            if isinstance(body.get("rate"), (int, float)):
                msg["rate"] = body["rate"]       # reading pace; the voice keeps its pitch
            resp = jarvis.request(msg, timeout=15)
            self.send_json(resp or {"ok": False, "error": "Jarvis isn't running"})
        elif self.path == "/api/wait":
            # Long-poll: returns when the line is done playing (or, with `lead`, about to be),
            # or after ~20 s (then ask again).
            try:
                line = int(body.get("id"))
            except (TypeError, ValueError):
                return self.send_json({"ok": False, "error": "needs a line id"}, 400)
            msg = {"cmd": "wait", "id": line, "timeout": 20}
            for key, top in (("timeout", 20), ("lead", 30)):
                if isinstance(body.get(key), (int, float)):
                    msg[key] = min(max(float(body[key]), 0.0), top)
            resp = jarvis.request(msg, timeout=30)
            self.send_json(resp or {"ok": False, "error": "Jarvis isn't running"})
        elif self.path == "/api/stop":
            resp = jarvis.request({"cmd": "stop"}, timeout=5)
            self.send_json(resp or {"ok": False, "error": "Jarvis isn't running"})
        elif self.path == "/api/render/cancel":
            resp = jarvis.request({"cmd": "cancel_render"}, timeout=5)
            self.send_json(resp or {"ok": False, "error": "Jarvis isn't running"})
        elif self.path == "/api/quit":
            # Shut down = everything: Jarvis (frees the GPU), then this page's server.
            had_jarvis = bool(jarvis.request({"cmd": "quit"}, timeout=5))
            self.send_json({"ok": True, "jarvis": had_jarvis})
            print("[jarvis-ui] shut down from the page", flush=True)
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        elif self.path == "/api/render":
            # Jarvis writes the wav straight into output/, the same place ./speak puts its renders.
            text = str(body.get("text", "")).strip()
            if body.get("markdown"):
                text = strip_markdown(text)
            if not text:
                return self.send_json({"ok": False, "error": "nothing to render"}, 400)
            voice = str(body.get("voice") or "")
            if voice in list_voices():
                text = f"[{voice}] {text}"   # who reads until a [voice] mark says otherwise
            OUTPUT.mkdir(parents=True, exist_ok=True)
            out = free_name(OUTPUT / (slug(str(body.get("name") or "conversation")) + ".wav"))
            msg = {"cmd": "render", "text": text, "out": str(out),
                   "my_breaths": bool(body.get("my_breaths"))}
            if isinstance(body.get("rate"), (int, float)):
                msg["rate"] = body["rate"]
            resp = jarvis.request(msg, timeout=None)
            if not resp or not resp.get("ok") or not out.exists():
                return self.send_json(resp or {"ok": False, "error": "Jarvis isn't running"}, 503)
            shown = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
            self.send_json({"ok": True, "file": str(shown), "seconds": resp.get("seconds")})
        elif self.path in ("/api/voices/commit", "/api/voices/untrack", "/api/voices/delete",
                           "/api/voices/rename"):
            # Every one of these moves the clip and its transcript together.
            known = list_voices()
            names = [v for v in (body.get("voices") or []) if isinstance(v, str)]
            if self.path.endswith("/rename"):
                names = [str(body.get("voice") or "")]
            missing = [v for v in names if v not in known]
            if not names or missing:
                return self.send_json(
                    {"ok": False, "error": f"no such voice: {', '.join(missing) or '(none given)'}"}, 400)
            if self.path.endswith("/rename"):
                ok, detail = rename_voice(names[0], str(body.get("name") or "").strip().lower())
            elif self.path.endswith("/untrack"):
                ok, detail = untrack_voices(names)
            elif self.path.endswith("/delete"):
                ok, detail = delete_voices(names)
            else:
                ok, detail = commit_voices(names)
            self.send_json({"ok": ok, "voices": names, "detail": detail, "error": "" if ok else detail},
                           200 if ok else 400)
        elif self.path == "/api/post":
            # The article, as Markdown, into posts/ — the text as it reads, marks and all.
            # With an id, it writes that same file again; without one, it takes a free name.
            text = str(body.get("text", "")).strip()
            if not text:
                return self.send_json({"ok": False, "error": "nothing to save"}, 400)
            POSTS.mkdir(parents=True, exist_ok=True)
            again = safe_path(POSTS, str(body.get("id") or ""), ".md")
            replacing = bool(again and again.exists())
            path = again if replacing else free_name(POSTS / (slug(str(body.get("name") or "post")) + ".md"))
            path.write_text(text + "\n", encoding="utf-8")
            shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
            self.send_json({"ok": True, "file": str(shown), "id": path.stem, "replaced": replacing})
        elif self.path == "/api/articles/save":
            name = str(body.get("name") or "").strip()
            # Keeps the file it already has; renaming changes the name inside it, not the file.
            path = article_path(str(body.get("id") or "") or slug(name))
            if not name or not path:
                return self.send_json({"ok": False, "error": "needs a name"}, 400)
            doc = body.get("article")
            data = clean_article(name, doc if isinstance(doc, dict) else {})
            ARTICLES.mkdir(exist_ok=True)
            path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            self.send_json({"ok": True, "id": path.stem})
        elif self.path in ("/api/articles/load", "/api/articles/delete"):
            path = article_path(str(body.get("id") or ""))
            if not path:
                return self.send_json({"ok": False, "error": "bad article id"}, 400)
            if self.path.endswith("/delete"):
                path.unlink(missing_ok=True)
                return self.send_json({"ok": True})
            if not path.exists():
                return self.send_json({"ok": False, "error": "that article isn't saved"}, 404)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                return self.send_json({"ok": False, "error": f"can't read {path.name} (broken JSON?)"}, 422)
            self.send_json({"ok": True, "article": clean_article(str(data.get("name") or path.stem), data)})
        elif self.path == "/api/conversations/save":
            name = str(body.get("name") or "").strip()
            # Re-saving what's loaded keeps its file; a new name gets a new one.
            path = conversation_path(str(body.get("id") or "") or slug(name))
            if not name or not path:
                return self.send_json({"ok": False, "error": "needs a name"}, 400)
            conv = body.get("conversation")
            data = clean_conversation(name, conv if isinstance(conv, dict) else {})
            CONVERSATIONS.mkdir(exist_ok=True)
            path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            self.send_json({"ok": True, "id": path.stem})
        elif self.path in ("/api/conversations/load", "/api/conversations/delete"):
            path = conversation_path(str(body.get("id") or ""))
            if not path:
                return self.send_json({"ok": False, "error": "bad conversation id"}, 400)
            if self.path.endswith("/delete"):
                path.unlink(missing_ok=True)
                return self.send_json({"ok": True})
            if not path.exists():
                return self.send_json({"ok": False, "error": "that conversation isn't saved"}, 404)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                return self.send_json({"ok": False, "error": f"can't read {path.name} (broken JSON?)"}, 422)
            self.send_json({"ok": True, "conversation": clean_conversation(str(data.get("name") or path.stem),
                                                                           data)})
        else:
            self.send_json({"ok": False, "error": "not found"}, 404)


def interrupted(*_):
    raise KeyboardInterrupt


def main() -> int:
    ap = argparse.ArgumentParser(description="A local web page for Jarvis.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="Don't open the page in a browser.")
    ap.add_argument("--no-start", action="store_true",
                    help="Don't start Jarvis (press Start on the page when you want it).")
    ap.add_argument("--keep-jarvis", action="store_true",
                    help="Leave Jarvis running when the page stops with Ctrl+C.")
    args = ap.parse_args()

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        print(f"[jarvis-ui] can't use port {args.port} ({e.strerror}); is the page already "
              f"running? Try --port.", file=sys.stderr)
        return 1
    server.allowed_hosts = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
    server.last_start = 0.0
    if not args.no_start:
        if jarvis.start_server():
            server.last_start = time.time()
            print("[jarvis-ui] starting Jarvis (loading Breeze, ~25 s; the page shows when it's ready)")
        else:
            print("[jarvis-ui] Jarvis is already running")
    url = f"http://127.0.0.1:{args.port}/"
    print(f"[jarvis-ui] {url}  (Shut down on the page, or Ctrl+C here, stops the page"
          f"{'' if args.keep_jarvis else ' and Jarvis'})")
    if not args.no_open:
        webbrowser.open_new_tab(url)
    for sig in (signal.SIGTERM, signal.SIGHUP):   # a kill or a closed terminal counts as Ctrl+C
        signal.signal(sig, interrupted)
    try:
        server.serve_forever()   # returns when Shut down is pressed on the page
    except KeyboardInterrupt:
        if not args.keep_jarvis and jarvis.request({"cmd": "quit"}, timeout=5):
            try:
                print("\n[jarvis-ui] shut Jarvis down too (--keep-jarvis leaves it running)")
            except OSError:
                pass   # the terminal is already gone
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
