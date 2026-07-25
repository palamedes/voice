---
name: say-fast
description: Speak text OUT LOUD with the fast, non-cloned Kokoro-82M voice (this voice project only) — like /say, but near-instant via the warm voice daemon. Use when the user says "/say-fast", "/jarvis", or wants to hear the fast/canned voice immediately rather than get a file.
---

# say-fast — speak text out loud, near-instantly (no saved file)

Speaks through the resident voice daemon (`scripts/voice_daemon.py`, Kokoro-82M).
The first call auto-starts the daemon (one-time model load, ~10s); every call
after that starts talking in well under a second. Nothing is saved.

## How
Run EXACTLY ONE command. Do NOT chain commands; a single statement is what the
permission allowlist matches (so it never prompts).

```bash
kokoro/.venv/bin/python scripts/voice_daemon.py --text "<the text>"
```

For a file instead of inline text, use `--file <path>` (still one command).
Keep it a single invocation beginning with
`kokoro/.venv/bin/python scripts/voice_daemon.py` so it stays auto-approved.

The command returns as soon as the daemon starts speaking (it keeps talking in
the background). Add `--wait` only if you need to block until playback ends
(e.g. before playing something else).

## Inputs
- **Text**: from the args / pasted message / a named file. If none, ask what to say.
- **Voice**: `--voice NAME` (`--list-voices`). Default `am_adam`.
- **Speed**: `--speed 1.2` etc.
- **Interrupt**: `--stop` cuts off whatever it's currently saying. A new say
  also interrupts the current one automatically.
- **Shutdown**: `--quit` stops the daemon (frees the model from RAM).

## Be quiet — this is the most important rule
`/say-fast` should feel like the computer just talking. Minimize all chatter:
- Do NOT preface with "I'll say X out loud" or narrate what you're about to do.
- Do NOT confirm afterward ("Said it!", "Done", "Did you hear it?") or ask any
  follow-up questions. No summaries, no emoji, no recap.
- Run the command, let the voice play, and stop. Ideally reply with nothing more
  than a brief acknowledgement only if something went wrong.
- The ONLY time to speak up is on failure (e.g. no audio device) — then say one
  short line and fall back to `/speak-fast` with the saved path.

## Notes
- Keep `/say-fast` for short, immediate stuff. For anything the user will reuse
  or publish, use `/speak-fast` (which saves to `output/`).
- Daemon log: `/tmp/voice_daemon.log` (check it if the daemon won't start).
