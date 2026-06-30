#!/usr/bin/env bash
# prep_ref.sh — extract a clean reference clip for F5-TTS voice cloning.
#
# Usage:
#   scripts/prep_ref.sh INPUT [START] [DURATION] [OUTPUT]
#
#   INPUT     any audio/video file (mp3, wav, m4a, mp4, mov, ...)
#   START     where to start, e.g. 0, 30, or 1:05  (default: 0)
#   DURATION  clip length in seconds                (default: 12)
#   OUTPUT    output wav path        (default: voice_samples/reference.wav)
#
# Tips for a GOOD reference clip:
#   * 8-15 seconds is the sweet spot. Longer is NOT better.
#   * One person (you), talking naturally, no music/background noise.
#   * End on a complete sentence with a natural pause.
set -euo pipefail

IN="${1:?Need an input audio/video file}"
START="${2:-0}"
DUR="${3:-12}"
OUT="${4:-voice_samples/reference.wav}"

mkdir -p "$(dirname "$OUT")"

# mono, 24kHz, loudness-normalized -> what F5-TTS works best with.
ffmpeg -hide_banner -loglevel error -y \
  -ss "$START" -t "$DUR" -i "$IN" \
  -ac 1 -ar 24000 \
  -af "loudnorm=I=-16:TP=-1.5:LRA=11,afftdn=nf=-25" \
  "$OUT"

echo "Wrote reference clip -> $OUT"
echo "Listen to it before using! Play with:  ffplay -autoexit '$OUT'"
