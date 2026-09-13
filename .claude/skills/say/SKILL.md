---
name: say
description: Speak text OUT LOUD in Jason's cloned voice (this voice project only) — like /speak, but it plays through the speakers via ffplay instead of saving a file. Use when the user says "/say", "say out loud", "read this aloud to me", or wants to hear it immediately rather than get a file.
---

# say — speak text out loud (no saved file)

Same engine as `/speak` (IndexTTS-2, `scripts/index_speak.py`), but it **plays the
audio out loud** and doesn't keep a file in `output/`.

## How
Run EXACTLY ONE command — generate to a fixed throwaway path and `--play` it.
Do NOT add a separate `rm` line or chain commands; a single statement is what the
permission allowlist matches (so it never prompts). The temp file is simply
overwritten on each call.

```bash
index-tts/.venv/bin/python scripts/index_speak.py --text "<the text>" --out /tmp/say.wav --play >/dev/null 2>&1
```

For a file instead of inline text, use `--file <path>` (still one command).
Keep it a single invocation beginning with
`index-tts/.venv/bin/python scripts/index_speak.py` so it stays auto-approved.

## Inputs (same as /speak)
- **Text**: from the args / pasted message / a named file. If none, ask what to say.
- **Engine**: Breeze TTS 2 by default (the script re-launches itself in Breeze's venv;
  same command, still auto-approved); add `--indextts` for IndexTTS-2 when asked.
- **Voice + window**: `--voice NAME` (`--list-voices`), or any voice name as a
  bare flag (`--calm`, `--muted`, `--presenter`, ...); `--ref-start SECS`,
  `--ref-secs SECS` (max 15s). Default voice `presenter`.
- **Delivery**: `--emotion neutral|happy|sad|angry`, `--rate 0.9` (slower),
  `--sentence-gap`/`--para-gap`/`--breath-gap` (ms). Pacing marks typed in the
  text are honored: `,,,` = breathe here, `[pause]`, `[pause 1.5]` — pass them
  through verbatim, don't "fix" `,,,` into a comma. `--my-breaths` = pause only
  at those marks and at line breaks (no automatic sentence/paragraph pauses).
- Do NOT use `--format ogg` here (no point — it's not being saved).

## Be quiet — this is the most important rule
`/say` should feel like the computer just talking. Minimize all chatter:
- Do NOT preface with "I'll say X out loud" or narrate what you're about to do.
- Do NOT confirm afterward ("Said it!", "Done", "Did you hear it?") or ask any
  follow-up questions. No summaries, no emoji, no recap.
- Run the command, let the voice play, and stop. Ideally reply with nothing more
  than a brief acknowledgement only if something went wrong.
- The ONLY time to speak up is on failure (e.g. no audio device) — then say one
  short line and fall back to `/speak` with the saved path.

## Notes
- Keep `/say` for short, immediate stuff. For anything the user will reuse or
  publish, use `/speak` (which saves to `output/`).
- No cleanup needed — `/tmp/say.wav` is reused and overwritten each call.
