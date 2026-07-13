# voice

Turn a blog post into audio of *you* reading it out loud. Give it text and a
10–15 second clip of your voice; it gives you back a clean audio file in your
voice. Runs entirely locally on an NVIDIA GPU — nothing is uploaded anywhere.

Two engines:

- **Cloned voice** ([IndexTTS-2](https://github.com/index-tts/index-tts)) —
  sounds like you. Slow: roughly a minute of compute per paragraph.
- **Fast voice** ([Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)) —
  stock synthetic voices, near-real-time. Same commands with `-fast` on the end.

Only clone your own voice, or someone who has explicitly said yes.

## The four commands

```sh
./speak "Hello, this is me."          # cloned voice → saved to output/
./say "Hello, this is me."            # cloned voice → out loud, nothing saved
./speak-fast "Hi, this is Adam."      # fast voice → saved to output/
./say-fast "Hi, this is Adam."        # fast voice → out loud
```

All four also exist as slash commands in a Claude Code session in this folder
(`/speak`, `/say`, `/speak-fast`, `/say-fast`, plus `/merge`), and as fish
functions so the bare names work without `./`.

## Voices

### List the available voices

```sh
./speak --list-voices
```

A "voice" is just an audio file in `voice_samples/` or
`voice_samples/processed/` — its name is the filename without the extension.
The default is `presenter`.

### Use a voice

Any listed voice name works as a bare flag, or via `--voice`:

```sh
./speak --calm "Same me, calmer read."
./speak --voice muted --file posts/my-post.md
```

### Add a new voice

1. Record (or find) 10–15 seconds of the person talking naturally. One voice,
   no music, no background noise, ending on a natural pause. Any format works
   as a source — wav, mp3, even an mp4 video.
2. Clean it into a reference clip:

   ```sh
   scripts/prep_ref.sh SOURCE.mp4 0 12 voice_samples/processed/myvoice.wav
   #                   input      │ │  output — filename becomes the voice name
   #                        start ┘ └ seconds to keep
   ```

3. Use it:

   ```sh
   ./speak --myvoice "Hello from the new voice."
   ```

The clip is the *entire* training step — there is no fine-tuning and no
transcript. If a voice sounds off, fix the clip: re-record, or slice a better
window from the source with different start/duration values. The model
ignores everything past 15 seconds, so longer is never better.

### What's the difference between `voice_samples/` and `voice_samples/processed/`?

- `voice_samples/` — raw source recordings, kept as-is (any format).
- `voice_samples/processed/` — cleaned reference clips made by
  `prep_ref.sh`: trimmed, mono, 24 kHz, loudness-normalized, noise-reduced.

Both folders show up in `--list-voices` and both work, but processed clips
sound better because the model gets a clean, consistent input. Convention:
keep the raw recording in `voice_samples/`, put the cleaned clip you actually
speak with in `processed/` under a short name (`calm`, `muted`, `presenter`).

## Common tasks

```sh
# Read a whole post, save the audio
./speak --file posts/my-post.md --out output/my-post.wav

# Also write a compressed .ogg for embedding in a blog (~15-20x smaller;
# a 3.5-minute post ≈ 1 MB)
./speak --file posts/my-post.md --out output/my-post.wav --format both

# Use a specific 15-second window of a reference (skip a 30s intro, take 12s)
./speak --voice ryan-reynolds --ref-start 30 --ref-secs 12 --text "..."

# Join two clips with a natural pause at the seam (works across engines/formats)
./merge output/intro.wav output/body.wav --out output/combined.wav

# Play anything back
ffplay -autoexit -nodisp output/my-post.wav
```

Input can be `--text "..."` or `--file post.md`; markdown is stripped
automatically. Output is loudness-normalized to -16 LUFS (podcast standard)
so every clip comes out at the same volume.

## Options reference

`./speak` / `./say` (wrappers around `scripts/index_speak.py`, the cloned voice):

```
  --file PATH / --text TEXT   what to read (markdown auto-stripped)
  --out PATH                  output path (default: output/index_out.wav)
  --voice NAME                reference voice (default: presenter); any name
                              also works as a bare flag: --calm, --muted, ...
  --ref PATH                  explicit reference clip path (overrides --voice)
  --ref-start / --ref-secs    which window of the reference to use (max 15s)
  --list-voices               list voices and exit
  --format {wav,ogg,both}     ogg = compressed Opus (default: wav)
  --bitrate RATE              Opus bitrate (default 48k)
  --play                      play out loud after generating
  --normalize / --no-normalize  loudness normalization (default: on)
  --lufs N                    target loudness (default -16)
  --emotion NAME              neutral (default), happy, sad, angry
  --emo-alpha A               emotion intensity (default 0.8)
  --fp16                      faster generation in half precision
```

`./speak-fast` / `./say-fast` (`scripts/fast_speak.py`, Kokoro-82M): same
`--file/--text/--out/--format/--play` flags, plus `--voice` (default
`am_adam`, see `--list-voices`) and `--speed` (default 1.0).

`./merge` (`scripts/merge_audio.py`): `--gap-ms` sets the pause at the seam
(default 450, a sentence-to-sentence pause; ~700+ for a paragraph break).

## Setup

- NVIDIA GPU (developed on an RTX 5070 Ti, 16 GB). Checkpoints are ~5.5 GB.
- `index-tts/.venv` — PyTorch 2.8 + CUDA 12.8 venv for the cloned voice
  (managed by `uv`; system Python 3.14 is too new for PyTorch).
- `kokoro/.venv` — separate venv for the fast engine (pip package only;
  first run downloads ~330 MB of weights).
- `ffmpeg` on PATH for playback, normalization, and merging.

## Layout

```
speak, say, speak-fast, say-fast, merge    bash wrappers (see above)
scripts/index_speak.py    cloned-voice narration (IndexTTS-2)
scripts/fast_speak.py     fast canned-voice narration (Kokoro-82M)
scripts/merge_audio.py    join two clips with a natural pause
scripts/prep_ref.sh       clean a reference clip out of any audio/video
scripts/audio_common.py   shared helpers (markdown stripping, normalization)
voice_samples/            raw voice recordings (+ processed/ cleaned clips)
posts/                    blog posts to read (.md or .txt)
output/                   generated audio
.claude/skills/           the slash commands (this project only)
index-tts/                IndexTTS-2 repo, its .venv, checkpoints/ (5.5 GB)
kokoro/.venv              the Kokoro-82M venv
```

## Acknowledgements

The cloning model is [IndexTTS-2](https://github.com/index-tts/index-tts) by
the Index team at Bilibili; the fast engine is
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) by hexgrad. This repo
is the plumbing around them. (F5-TTS and Zonos were evaluated and removed:
F5 mispronounced words with no way to fix it, Zonos didn't sound like me.)
