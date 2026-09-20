---
name: jarvis
description: Speak text OUT LOUD in a cloned voice through the always-loaded Breeze server (this voice project only) — like /say, but it starts talking in a second or two once the server is up. Use when the user says "/jarvis", "jarvis, say …", or wants the resident cloned voice, optionally in a named voice (e.g. "jarvis as art-bell").
---

# jarvis — the resident cloned voice (no saved file)

`scripts/jarvis_daemon.py` keeps Breeze TTS 2 loaded in a background server
(`/tmp/jarvis.sock`) until it's quit. If it isn't running, the command starts it
first (~25 s), then speaks.

## How
Run EXACTLY ONE command — a single statement:

```bash
breeze-tts/.venv/bin/python scripts/jarvis_daemon.py --text "<the text>"
```

- **Voice**: add `--voice NAME` (exact name from `--list-voices`). It sticks for
  later lines until changed; default `jason-ellis-presenter`.
- **Pacing / sounds**: `,,,`, `[pause 1]`, `(sighs)`, `[voice]` switches all work
  as in /speak; keep them verbatim. `--my-breaths` pauses only at marks and line
  breaks.
- **Control**: `--stop` stops talking, `--status` reports whether it's up and in
  which voice, `--quit` shuts it down and frees ~8 GB of GPU memory. A new line
  interrupts the current one.
- The command returns once the line is queued; add `--wait` to block until it
  finishes speaking.

## Be quiet — this is the most important rule
Like /say: run the command and stop. No preface, no "Done", no follow-up
questions. Only speak up if it fails — then one short line (check
`/tmp/jarvis.log`) and offer `/say` instead.
