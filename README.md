# voice

Give it a blog post and a 15-second clip of you talking. It gives you back
audio of *you* reading that post out loud, in your own voice, ready to embed
next to the article.

```sh
./speak "Hello, this is me. Well, it's AI me, but close enough."
```

Built on [IndexTTS-2](https://github.com/index-tts/index-tts) for the voice
cloning, with [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) as a
fast second engine for when you don't need the clone. Everything runs locally
on a normal gaming GPU; nothing is uploaded anywhere.

## What is this, in plain terms?

You know how some blogs have a "listen to this article" button? This makes
those recordings, except the voice reading the article is yours. You need
three things:

1. **Something to read.** A blog post, a paragraph, whatever — markdown or
   plain text. Markdown formatting is stripped automatically before it's
   spoken.
2. **A reference clip of your voice.** One clean 10–15 second recording of
   you talking naturally. No music, no background noise, ends on a natural
   pause. That's the entire "training" step — there isn't one. The model
   clones zero-shot from the clip.
3. **An NVIDIA graphics card.** Developed and tested on an RTX 5070 Ti
   (16 GB, Blackwell). The model checkpoints are about 5.5 GB.

What you get back is a single clean audio file — the model handles long-form
segmentation internally, so a whole post comes out as one continuous read
with no stitched-together seams, loudness-normalized to the podcast-standard
-16 LUFS so every clip comes out at the same volume.

Two honest caveats. First, the cloned voice is slow: about a minute of
compute per paragraph, because zero-shot cloning is expensive and the
checkpoint reloads every run. Kick off a post, get coffee. Second, only
clone **your own** voice, or someone who has explicitly said yes. The repo
having a `ryan-reynolds.mp3` in it is for engine testing, not an ethics
statement.

**If you just want speed**, the second engine (Kokoro-82M) reads in
near-real-time with stock synthetic voices — nobody real, names like
`am_adam` and `af_heart`. Same commands with `-fast` stuck on the end.

## Quick start

```sh
git clone git@github.com:palamedes/voice.git && cd voice
# set up index-tts/.venv and kokoro/.venv (see Environment below), then:

./speak "Hello, this is me."          # cloned voice → saved to output/
./say "Hello, this is me."            # cloned voice → out loud, nothing saved
./speak-fast "Hi, this is Adam."      # fast canned voice → saved to output/
./say-fast "Hi, this is Adam."        # fast canned voice → out loud
```

Or, in a Claude Code session in this folder, the same four exist as slash
commands — `/speak`, `/say`, `/speak-fast`, `/say-fast` — plus `/merge` to
join two clips. Or just paste text and ask it to read it.

Fish shell functions (`~/.config/fish/functions/{speak,speak-fast,say,say-fast,merge}.fish`)
wrap the scripts so the bare commands work from the project directory
without the `./`.

## Examples

```sh
# The basics: read a whole post, save the audio
index-tts/.venv/bin/python scripts/index_speak.py \
    --file posts/my-post.md --out output/my-post.wav

# Compressed for uploading to a blog: also write an .ogg (Opus), ~15-20x
# smaller than the wav. A 3.5-minute post becomes roughly a 1 MB file.
index-tts/.venv/bin/python scripts/index_speak.py \
    --file posts/my-post.md --out output/my-post.wav --format both

# Pick a different reference voice by name
index-tts/.venv/bin/python scripts/index_speak.py --list-voices
index-tts/.venv/bin/python scripts/index_speak.py \
    --voice calm --text "Same me, calmer read." --out output/demo.wav

# The reference is capped at 15 seconds — anything past that is silently
# ignored by the model — but you can choose WHICH 15 seconds. Here: start
# 30s in (skip an intro), use 12s of it.
index-tts/.venv/bin/python scripts/index_speak.py \
    --voice ryan-reynolds --ref-start 30 --ref-secs 12 \
    --text "Cloned from a chosen slice of the reference." --out output/demo.wav

# Fast engine: near-real-time, canned voice, same flags
kokoro/.venv/bin/python scripts/fast_speak.py \
    --file posts/my-post.md --out output/my-post_fast.wav

# Join two clips (any mix of engines/formats/sample rates) with a natural
# sentence-to-sentence pause at the seam instead of an abrupt cut
python3 scripts/merge_audio.py output/intro.wav output/body.wav \
    --out output/combined.wav

# Play anything back
ffplay -autoexit -nodisp output/my-post.wav
```

**What actually controls the clone quality:** the reference clip, and
nothing else. There's no transcript to provide (the model doesn't take one),
no fine-tuning, no settings that make it "more like you." A clean,
natural-sounding 10–15 seconds beats a longer clip every time, because the
model hard-truncates at 15 seconds anyway. If a voice sounds off, fix the
clip: re-record it, or use `--ref-start`/`--ref-secs` to slice a better
window out of what you have.

To make a new reference clip from any audio or video:

```sh
scripts/prep_ref.sh SOURCE.mp4 0 12 voice_samples/processed/myvoice.wav
#                    file       ^start ^seconds  ^output
```

Then use it with `--ref voice_samples/processed/myvoice.wav`, or drop it in
`voice_samples/` and it shows up in `--list-voices` by name. The current
default is `presenter`.

## Why IndexTTS-2 (and not the others we tried)

We evaluated three engines on the two things that matter: **does it sound
like me**, and **does it pronounce words correctly**.

| Engine | Likeness | Pronunciation | Verdict |
|--------|----------|---------------|---------|
| F5-TTS | good | ❌ no control (said "jarring" as "jerring") | removed |
| Zonos  | weak (only good when it leaked the reference audio) | ✅ via eSpeak | removed |
| **IndexTTS-2** | ✅ good | ✅ accurate (low error rate) | **chosen** |

IndexTTS-2 also handles long-form segmentation internally, so whole posts
come out as one clean file. F5-TTS and Zonos have been uninstalled;
IndexTTS-2 is the only cloning engine.

## Options reference

`scripts/index_speak.py` — the cloned voice:

```
  --file PATH / --text TEXT   input post file, or inline text (markdown auto-stripped)
  --out PATH                  output path (default: output/index_out.wav)
  --voice NAME                reference voice by name (default: presenter;
                              see --list-voices)
  --ref PATH                  explicit reference clip path (overrides --voice)
  --ref-start SECS            seconds into the reference to start (skip an intro)
  --ref-secs SECS             seconds of reference to use — max 15 (model caps there)
  --list-voices               list available reference voices and exit
  --format {wav,ogg,both}     ogg is compressed Opus, ~15-20x smaller (default: wav)
  --bitrate RATE              Opus bitrate (default 48k; 32k smaller, 64k nicer)
  --play                      play out loud (ffplay) after generating — powers /say
  --normalize / --no-normalize  loudness-normalize output (default: on)
  --lufs N                    target loudness (default -16, podcast standard)
  --emotion NAME              neutral (default), happy, sad, angry
  --emo-alpha A               emotion intensity when not neutral (default 0.8)
  --seg-tokens N              max tokens per internal segment (default 120)
  --gap-ms MS                 silence between internal segments (default 200)
  --fp16                      faster generation in half precision
```

`scripts/fast_speak.py` — the fast canned voice (Kokoro-82M):

```
  --file / --text / --out / --format / --play / --normalize / --lufs
                              same as above (default out: output/fast_out.wav)
  --voice NAME                canned voice (default am_adam; see --list-voices)
  --speed S                   speech speed multiplier (default 1.0)
```

First Kokoro run downloads ~330 MB of weights from Hugging Face; cached
after that.

`scripts/merge_audio.py` — joining two clips (plain ffmpeg + stdlib, no venv
needed). It trims whatever silence already exists at the join on both sides,
then inserts one consistent gap:

```
  --gap-ms MS                 pause at the seam (default 450, a natural
                              sentence-to-sentence pause; ~700+ for a
                              paragraph break)
  --out / --format / --bitrate / --normalize / --lufs   same as above
                              (default out: output/merged.wav)
```

## Environment

Python venv at `index-tts/.venv` (managed by `uv`), PyTorch 2.8 + CUDA 12.8.
The system Python (3.14) is too new for PyTorch, which is why everything
runs inside that venv. Kokoro gets its own venv at `kokoro/.venv` (pip
package only, no repo clone needed). `ffmpeg` on PATH for playback,
normalization, and merging.

## Layout

```
speak, say            bash wrappers: cloned voice, save / speak out loud
speak-fast, say-fast  bash wrappers: fast canned voice, save / speak out loud
merge                 bash wrapper for joining two clips
scripts/index_speak.py    cloned-voice narration (IndexTTS-2)
scripts/fast_speak.py     fast canned-voice narration (Kokoro-82M)
scripts/merge_audio.py    join two clips with a natural pause at the seam
scripts/audio_common.py   shared helpers (markdown stripping, normalization)
scripts/prep_ref.sh       make a clean reference clip from any audio/video
voice_samples/        reference voice clips (+ processed/ normalized versions)
posts/                blog posts to read (.md or .txt)
output/               generated audio
.claude/skills/       the /speak, /say, /speak-fast, /say-fast, /merge
                      slash commands (this project only)
index-tts/            the IndexTTS-2 repo, its .venv, checkpoints/ (5.5 GB)
kokoro/.venv          the Kokoro-82M venv
```

## Notes

- First run loads ~5.5 GB of checkpoints; generation after that is ~1.3x
  realtime.
- Pronunciation is reliable. For a rare wrong word, IndexTTS-2 supports
  pinyin-style annotation (see `checkpoints/pinyin.vocab`) — mainly for
  Chinese.
- Project history and gotchas are tracked in Claude's project memory.

## Acknowledgements

The cloning model is [IndexTTS-2](https://github.com/index-tts/index-tts)
by the Index team at Bilibili; the fast engine is
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) by hexgrad. This
repo is the plumbing around them: CLI scripts, loudness normalization,
reference-clip prep, and Claude Code slash commands.
