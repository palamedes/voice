---
name: merge
description: Merge two audio clips (from this voice project) into one file, with a natural sentence-to-sentence pause at the seam instead of an abrupt cut or a stacked double-silence. Use when the user says "/merge", wants to join two generated clips, or combine an intro/outro voice with a body voice.
---

# merge — join two audio clips with a natural pause at the seam

Combines two audio files in `/home/jellis/Projects/voice` (e.g. two `/speak`
or `/speak-fast` outputs) into one, using `scripts/merge_audio.py` (plain
system `python3` — ffmpeg only, no venv needed).

## Why not just `ffmpeg concat`
Naively concatenating leaves whatever silence each clip already happens to
have at its edges — sometimes too tight (abrupt), sometimes too long (two
clips' trailing/leading silence stacking). This script trims each clip's
existing edge silence first, then inserts one consistent, natural-sounding
gap.

## Inputs
- **clip_a, clip_b**: two audio file paths (positional args, any order the
  user wants them joined in). Formats can differ (wav/ogg) and even sample
  rates can differ — the script resamples clip B to match clip A.
- **`--gap-ms`**: pause length at the seam. Default `450` (a natural
  sentence-to-sentence pause). Use something longer like `700-900` if the
  join is a paragraph break, or shorter (`200-300`) for a tighter, same-breath
  join.
- **`--out`**: output path (default `output/merged.wav`).
- **`--format wav|ogg|both`** / **`--bitrate`**: same conventions as the other
  scripts.
- **`--normalize` / `--no-normalize`**, **`--lufs`**: loudness-normalize the
  merged result (default on, `-16` LUFS) so a seam between two differently-
  sourced clips doesn't have a volume jump.

## Steps
1. Confirm both input files exist (ask the user for paths if unclear —
   check `output/` for recent narrations if they just say "merge the last
   two clips").
2. Pick an output path in `output/` (don't silently overwrite an existing
   file — add a numeric suffix if needed).
3. Run from the project root:
   ```bash
   python3 scripts/merge_audio.py <clip_a> <clip_b> --out output/<name>.wav
   ```
4. Confirm the output path + duration, and tell the user to play it:
   `! ffplay -autoexit -nodisp output/<name>.wav`

## Notes
- There's also a standalone `./merge` bash script (and `merge` fish function)
  for using this outside Claude Code.
- Details on the gap-length reasoning are in README.md and project memory.
