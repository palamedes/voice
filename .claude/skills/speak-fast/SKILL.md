---
name: speak-fast
description: Narrate text quickly with a fast, non-cloned voice (Kokoro-82M, this voice project only). Use when the user wants speed over voice likeness, doesn't need Jason's cloned voice, or says "/speak-fast". Produces audio in output/.
---

# speak-fast — quick narration with a canned voice (not a clone)

Generate audio of the user's text in `/home/jellis/Projects/voice`, using
**Kokoro-82M** instead of the default cloned-voice engine.

## Engine: Kokoro-82M (fast, not a clone)
Use `scripts/fast_speak.py` (venv: `kokoro/.venv`). Kokoro has small, fast,
built-in canned voices — no reference clip, no cloning, generation is close
to real-time. This is NOT Jason's voice and not any real person's voice; it's
a stock synthetic voice. Use this when the user cares more about speed than
about it sounding like them (contrast with `/speak`, which clones Jason's
actual voice via IndexTTS-2 but takes much longer).

## Inputs
- **Text**: from the skill args, the pasted message, or a file the user names
  (e.g. `posts/foo.md`). If none present, ask: "What text should I read?"
- **Voice**: `--voice NAME` (run `--list-voices` to see them; default
  `am_adam`, American English male — Jason's choice). Other options include
  `af_heart` (American female, Kokoro's highest-quality voice),
  `am_michael`/`am_puck` (American male), `bf_emma` (British female),
  `bm_george` (British male).
- **Speed**: `--speed 1.2` etc. (1.0 = normal).
- **Format**: default wav. If the user wants a small file, add `--format ogg`
  (Opus, ~15-20x smaller) or `--format both`. Bitrate via `--bitrate 48k`.

## Steps
1. If the text is more than a sentence or two, write it to `posts/<slug>.md`
   first (avoids shell-quoting issues), then use `--file`. Short snippets can
   use `--text "..."`.
2. Pick an output path in `output/` (derive from the file/slug; don't silently
   overwrite — add a numeric suffix if it exists).
3. Run from the project root:
   ```bash
   kokoro/.venv/bin/python scripts/fast_speak.py \
       --file posts/<slug>.md \
       --out output/<slug>_fast.wav
   ```
4. Confirm the output path + duration, and tell the user to play it:
   `! ffplay -autoexit -nodisp output/<slug>_fast.wav`

## Notes
- First call after a fresh setup downloads ~330MB of model weights from
  Hugging Face; after that it's cached and generation is fast every time.
- If the user wants this played out loud immediately instead of saved, add
  `--play` to the command (mirrors how `/say` uses `--play` with `index_speak.py`).
- Details on why this engine was added (speed vs. the cloned-voice default)
  are in README.md and project memory.
