# Voice — read my blog posts in my own (AI-cloned) voice

Local, offline narration of blog posts in Jason's cloned voice, using
**[IndexTTS-2](https://github.com/index-tts/index-tts)**. Give it text + a short
reference clip of your voice, and it speaks the text as you — with correct
pronunciation and clean long-form output.

Runs entirely locally on the RTX 5070 Ti (16 GB, Blackwell). Nothing is uploaded.

---

## Why IndexTTS-2 (and not the others we tried)

We evaluated three engines on two things that matter: **does it sound like me**,
and **does it pronounce words correctly**.

| Engine | Likeness | Pronunciation | Verdict |
|--------|----------|---------------|---------|
| F5-TTS | good | ❌ no control (said "jarring" as "jerring") | removed |
| Zonos  | weak (only good when it leaked the reference audio) | ✅ via eSpeak | removed |
| **IndexTTS-2** | ✅ good | ✅ accurate (low error rate) | **chosen** |

IndexTTS-2 also handles **long-form segmentation internally**, so whole posts come
out as one clean file with no stitched-together seams. F5-TTS and Zonos have been
uninstalled; IndexTTS-2 is the only engine.

---

## Layout

- `index-tts/`            — the IndexTTS-2 repo, its `.venv`, and `checkpoints/` (5.5 GB)
- `scripts/index_speak.py`— the narration script (text/post → audio)
- `scripts/prep_ref.sh`   — make a clean reference clip from any audio/video
- `voice_samples/`        — reference voice clips (+ `processed/` normalized versions)
- `posts/`                — blog posts to read (.md or .txt)
- `output/`               — generated audio
- `.claude/skills/speak/` — the `/speak` skill (this project only)

Environment: Python venv at `index-tts/.venv` (managed by `uv`), PyTorch
2.8 + CUDA 12.8. The system Python (3.14) is too new for PyTorch, which is why
everything runs inside that venv.

---

## Usage

### Quick way — the `/speak` and `/say` skills
In a Claude Code session in this folder:
- `/speak <text>` — generate audio and **save** it to `output/`.
- `/say <text>` — speak it **out loud** immediately (via ffplay), no saved file.

Or just paste text and ask me to read it. New slash commands need a one-time
Claude Code reload to register.

### Direct way — run the script
```bash
index-tts/.venv/bin/python scripts/index_speak.py \
    --file posts/my-post.md \
    --out output/my-post.wav
```
Inline text instead of a file:
```bash
index-tts/.venv/bin/python scripts/index_speak.py \
    --text "This is me, but it's AI." \
    --out output/test.wav
```
Play it:
```bash
ffplay -autoexit -nodisp output/my-post.wav
```

### Options
| Flag | Default | Meaning |
|------|---------|---------|
| `--file` / `--text` | — | input post file, or inline text (markdown auto-stripped) |
| `--out` | `output/index_out.wav` | output path |
| `--voice` | `conversational` | reference voice by name (see `--list-voices`) |
| `--ref` | — | explicit reference clip path (overrides `--voice`) |
| `--ref-start` | `0` | seconds into the reference to start listening (skip an intro) |
| `--ref-secs` | (whole) | seconds of reference to use — **max 15** (model caps there) |
| `--list-voices` | — | list available reference voices and exit |
| `--format` | `wav` | `wav`, `ogg` (compressed Opus, ~15-20x smaller), or `both` |
| `--bitrate` | `48k` | Opus bitrate for ogg (`32k` smaller, `64k` higher quality) |
| `--play` | off | play the audio out loud (ffplay) after generating — powers `/say` |
| `--normalize` / `--no-normalize` | on | loudness-normalize output to a consistent level (fixes voice-to-voice volume swings) |
| `--lufs` | `-16` | target integrated loudness (broadcast/podcast standard for speech) |
| `--emotion` | `neutral` | `neutral`, `happy`, `sad`, `angry` |
| `--emo-alpha` | `0.8` | emotion intensity (when not neutral) |
| `--seg-tokens` | `120` | max tokens per internal segment |
| `--gap-ms` | `200` | silence between internal segments |
| `--fp16` | off | faster generation in half precision |

Example — whole post, compressed for upload:
```bash
index-tts/.venv/bin/python scripts/index_speak.py \
    --file posts/my-post.md --out output/my-post.wav --format both
```
Roughly a 3.5-minute post → ~3 min generation, a full WAV plus a ~1 MB `.ogg`.

Example — pick a voice and which 15s window of it to clone:
```bash
index-tts/.venv/bin/python scripts/index_speak.py --list-voices
index-tts/.venv/bin/python scripts/index_speak.py \
    --voice ryan-reynolds --ref-start 30 --ref-secs 12 \
    --text "Cloned from a chosen slice of the reference." --out output/demo.wav
```
The reference is capped at **15 seconds** — anything longer is ignored — but
`--ref-start` lets you choose *which* window (e.g. skip an intro).

---

## Making a new reference clip

The reference clip defines the voice. A single clean 10-16s clip of you talking
naturally (no music/background, ends on a natural pause) works best.

```bash
scripts/prep_ref.sh SOURCE.mp4 0 12 voice_samples/processed/myvoice.wav
#                    file       ^start ^seconds  ^output
```
Then point at it with `--ref voice_samples/processed/myvoice.wav`. The current
default is `conversational.wav`.

---

## Notes

- First run loads ~5.5 GB of checkpoints; generation after that is ~1.3x realtime.
- Pronunciation is reliable. For a rare wrong word, IndexTTS-2 supports
  pinyin-style annotation (see `checkpoints/pinyin.vocab`) — mainly for Chinese.
- Ethics: only clone **your own** voice (or with explicit consent).
- Project history and gotchas are tracked in Claude's project memory.
