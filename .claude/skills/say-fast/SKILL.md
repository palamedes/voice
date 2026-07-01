---
name: say-fast
description: Speak text OUT LOUD with the fast, non-cloned Kokoro-82M voice (this voice project only) — like /say, but uses /speak-fast's engine instead of the cloned voice. Use when the user says "/say-fast" or wants to hear the fast/canned voice immediately rather than get a file.
---

# say-fast — speak text out loud with the fast canned voice (no saved file)

Same engine as `/speak-fast` (Kokoro-82M, `scripts/fast_speak.py`), but it
**plays the audio out loud** and doesn't keep a file in `output/`.

## How
Run EXACTLY ONE command — generate to a fixed throwaway path and `--play` it.
Do NOT add a separate `rm` line or chain commands; a single statement is what the
permission allowlist matches (so it never prompts). The temp file is simply
overwritten on each call.

```bash
kokoro/.venv/bin/python scripts/fast_speak.py --text "<the text>" --out /tmp/say_fast.wav --play >/dev/null 2>&1
```

For a file instead of inline text, use `--file <path>` (still one command).
Keep it a single invocation beginning with
`kokoro/.venv/bin/python scripts/fast_speak.py` so it stays auto-approved.

## Inputs (same as /speak-fast)
- **Text**: from the args / pasted message / a named file. If none, ask what to say.
- **Voice**: `--voice NAME` (`--list-voices`). Default `am_adam`.
- **Speed**: `--speed 1.2` etc.

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
- No cleanup needed — `/tmp/say_fast.wav` is reused and overwritten each call.
