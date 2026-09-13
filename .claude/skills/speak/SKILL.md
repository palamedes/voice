---
name: speak
description: Narrate text in Jason's cloned voice (this voice project only). Use when the user wants to generate spoken audio of some text / a blog post / pasted text in their own voice, or says things like "say this", "read this aloud", "/speak". Produces audio in output/.
---

# speak — turn text into Jason's cloned voice

Generate audio of the user's text in `/home/jellis/Projects/voice`.

## Default engine: Breeze TTS 2 (Jason's pick, 2026-09-12)
Use `scripts/index_speak.py`, always launched with the `index-tts/.venv` python —
for Breeze it re-launches itself in `breeze-tts/.venv`. Text is fed one sentence /
marked phrase at a time with explicit pauses between. Default reference is a single
clean clip (`voice_samples/processed/presenter.wav`). The first use of a voice
transcribes its reference into `<voice>.txt` beside the clip (Whisper). Breeze
performs sounds written in parentheses — `(sighs)`, `(laughs)`, `(clears throat)`,
`(whispers)`, `(shouts)`… (34 tags; exact spellings in README "Breeze sounds") —
keep the user's parentheses as written, and don't add new ones to the text.
Breeze runs in fast mode by default (~9 s warm-up, then ~5x faster rendering);
`--no-fast` is the plain path — only if the user asks.

**Second engine: IndexTTS-2** — add `--indextts` when the user asks for it. It also
clones Jason well, pronounces reliably, and has emotion presets; `--emotion`/`--fp16`/
`--seg-tokens`/`--gap-ms` are IndexTTS-only.

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
  `--rate 0.9` (slower, pitch kept), `--sentence-gap`/`--para-gap`/`--breath-gap` (ms).
- **Pacing marks** in the text are the user's control over breaths — preserve them
  verbatim when writing the text to `posts/`: `,,,` = breathe here, `[breath]`,
  `[pause]` (0.7s), `[pause 1.5]` / `[pause 800ms]`. Blank lines = paragraph pause.
  `--my-breaths` = pause ONLY at those marks and at line breaks (every line break
  is a breath and they stack — an empty line = 2 breaths; a mark at a line end
  stands in for that line's first break; no automatic sentence/paragraph pauses,
  and the model's own mid-phrase pauses are cut to 0.1s) — so keep the user's
  line breaks and blank lines exactly when writing text to `posts/`.
  `--auto-breaths` is the default.
  `[voice-name]` (exact name from `--list-voices`) switches voices from that point
  until the next switch — keep these verbatim too.
  `--dry-run` prints the chunks + pauses (and who reads each) without rendering.

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
   Add `--format ogg` if a compressed file is wanted. A 5-minute post takes a
   couple of minutes; consider running in the background and reporting when done.
4. Confirm the output path + duration, and tell the user to play it:
   `! ffplay -autoexit -nodisp output/<slug>.wav`  (or `.ogg`).

## Notes
- Pronunciation is reliable; if a rare word is wrong, IndexTTS-2 supports
  pinyin-style annotation for fixes (see checkpoints/pinyin.vocab) — mainly Chinese.
- Cloning engines: Breeze TTS 2 (default) and IndexTTS-2 (`--indextts`). F5-TTS,
  Zonos, CosyVoice3 and IndexTTS-2.5 were tried and removed. For a fast
  non-cloned voice use `/speak-fast` (Kokoro-82M).
- Details + history in README.md / project memory.
