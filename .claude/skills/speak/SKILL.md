---
name: speak
description: Narrate text in Jason's cloned voice (this voice project only). Use when the user wants to generate spoken audio of some text / a blog post / pasted text in their own voice, or says things like "say this", "read this aloud", "/speak". Produces audio in output/.
---

# speak — turn text into Jason's cloned voice

Generate audio of the user's text in `/home/jellis/Projects/voice`.

## Default engine: IndexTTS-2 (the winner)
Use `scripts/index_speak.py` (venv: `index-tts/.venv`). It clones Jason's voice
well AND pronounces correctly (real g2p — fixed the "jarring" problem), and it
handles long-form segmentation internally (no manual chunk-stitching). Default
reference is a single clean clip (`voice_samples/processed/presenter.wav`).

## Inputs
- **Text**: from the skill args, the pasted message, or a file the user names
  (e.g. `posts/foo.md`). If none present, ask: "What text should I read?"
- **Reference voice** (which voice to clone): `--voice NAME` (run
  `--list-voices` to see them; default `presenter`). Any voice name also works
  as a bare flag: `--calm`, `--muted`, `--presenter`, etc. The user can say e.g.
  "use the calm voice". For a window of a longer clip: `--ref-start SECS`
  (where to start) and `--ref-secs SECS` (how long; **max 15s** — the model caps
  there). Or `--ref PATH` for an explicit file. Example: "use ryan-reynolds,
  start at 30 seconds, listen for 12" → `--voice ryan-reynolds --ref-start 30 --ref-secs 12`.
- **Format**: default wav. If the user wants a small file, add `--format ogg`
  (Opus, ~15-20x smaller) or `--format both`. Bitrate via `--bitrate 48k`.
- **Delivery** (only if asked): `--emotion neutral|happy|sad|angry` (+ `--emo-alpha`),
  `--seg-tokens` (lower = safer segmentation), `--gap-ms` (silence between segments).

## Steps
1. If the text is more than a sentence or two, write it to `posts/<slug>.md`
   first (avoids shell-quoting issues), then use `--file`. Short snippets can use
   `--text "..."`.
2. Pick an output path in `output/` (derive from the file/slug; don't silently
   overwrite — add a numeric suffix if it exists).
3. Run from the project root:
   ```bash
   index-tts/.venv/bin/python scripts/index_speak.py \
       --file posts/<slug>.md \
       --out output/<slug>.wav
   ```
   Add `--format ogg` if a compressed file is wanted. Long posts take a couple
   minutes (~RTF 1.3); consider running in the background and reporting when done.
4. Confirm the output path + duration, and tell the user to play it:
   `! ffplay -autoexit -nodisp output/<slug>.wav`  (or `.ogg`).

## Notes
- Pronunciation is reliable; if a rare word is wrong, IndexTTS-2 supports
  pinyin-style annotation for fixes (see checkpoints/pinyin.vocab) — mainly Chinese.
- F5-TTS and Zonos have been uninstalled; IndexTTS-2 is the only cloning
  engine. For a fast non-cloned voice use `/speak-fast` (Kokoro-82M).
- Details + history in README.md / project memory.
