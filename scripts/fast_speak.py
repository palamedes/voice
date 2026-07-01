#!/usr/bin/env python3
"""
fast_speak.py — narrate text with a fast, non-cloned voice (Kokoro-82M).

Why a second engine: IndexTTS-2 (index_speak.py) clones Jason's actual voice,
but that cloning + checkpoint reload makes it slow (~1 min/paragraph). Kokoro-82M
is a small model with built-in canned voices (not a clone of anyone real) that
generates close to real-time, for when speed matters more than it being *your*
voice.

Run with the Kokoro venv:
  kokoro/.venv/bin/python scripts/fast_speak.py \
      --file posts/ai-slop-youtube.md --out output/ai-slop-youtube_fast.wav
"""
import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_common import normalize_loudness, strip_markdown

SAMPLE_RATE = 24000

# Curated English voices (name -> lang/accent/gender/quality). Full list has
# 50+ voices across languages; these are the ones worth narrating an English
# blog post in. Grades are from Kokoro's own quality ranking.
VOICES = {
    "am_adam":     "American English, male (default)",
    "af_heart":    "American English, female (best overall quality)",
    "af_bella":    "American English, female",
    "af_nicole":   "American English, female",
    "am_michael":  "American English, male",
    "am_puck":     "American English, male",
    "bf_emma":     "British English, female",
    "bm_george":   "British English, male",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Fast narration with a canned Kokoro-82M voice (not a clone).")
    src = ap.add_mutually_exclusive_group(required=False)
    src.add_argument("--file", type=Path)
    src.add_argument("--text", type=str)
    ap.add_argument("--out", type=Path, default=Path("output/fast_out.wav"))
    ap.add_argument("--voice", default="am_adam", choices=list(VOICES),
                    help="Canned voice (see --list-voices). Default: am_adam.")
    ap.add_argument("--list-voices", action="store_true", help="List available voices and exit.")
    ap.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier.")
    ap.add_argument("--gap-ms", type=int, default=150, help="Silence between internal chunks.")
    ap.add_argument("--format", choices=["wav", "ogg", "both"], default="wav",
                    help="Output format. 'ogg' = compressed Opus (~15-20x smaller).")
    ap.add_argument("--bitrate", default="48k", help="Opus bitrate for ogg (e.g. 32k, 48k, 64k).")
    ap.add_argument("--play", action="store_true", help="Play the audio out loud (ffplay) after generating.")
    ap.add_argument("--normalize", action=argparse.BooleanOptionalAction, default=True,
                    help="Loudness-normalize output to a consistent level (default on).")
    ap.add_argument("--lufs", type=float, default=-16.0, help="Target integrated loudness (LUFS).")
    ap.add_argument("--no-markdown", action="store_true")
    args = ap.parse_args()

    if args.list_voices:
        print("Available voices:")
        for name, desc in VOICES.items():
            print(f"  {name:12s} {desc}")
        return 0

    if args.text is None and args.file is None:
        print("ERROR: provide --text or --file (or --list-voices).", file=sys.stderr)
        return 1

    raw = args.text if args.text is not None else args.file.read_text(encoding="utf-8")
    text = raw if args.no_markdown else strip_markdown(raw)
    if not text.strip():
        print("ERROR: nothing to speak.", file=sys.stderr)
        return 1

    print(f"[fast_speak] {len(text)} chars. Loading Kokoro-82M ({args.voice})...")
    from kokoro import KPipeline

    lang_code = args.voice[0]  # 'a' American, 'b' British — first letter of the voice name
    pipeline = KPipeline(lang_code=lang_code)

    gap = np.zeros(int(SAMPLE_RATE * args.gap_ms / 1000), dtype=np.float32)
    chunks = []
    for i, (_gs, _ps, audio) in enumerate(pipeline(text, voice=args.voice, speed=args.speed, split_pattern=r"\n+")):
        if i > 0:
            chunks.append(gap)
        chunks.append(audio)
    if not chunks:
        print("ERROR: Kokoro produced no audio.", file=sys.stderr)
        return 1
    audio = np.concatenate(chunks)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    wav_path = args.out.with_suffix(".wav")
    sf.write(str(wav_path), audio, SAMPLE_RATE)

    if args.normalize:
        normalize_loudness(wav_path, target_i=args.lufs)

    outputs = [wav_path]
    if args.format in ("ogg", "both"):
        ogg_path = args.out.with_suffix(".ogg")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav_path),
             "-c:a", "libopus", "-b:a", args.bitrate, str(ogg_path)],
            check=True,
        )
        outputs.append(ogg_path)
        if args.format == "ogg":
            wav_path.unlink()              # drop the big wav, keep only the ogg
            outputs = [ogg_path]

    for p in outputs:
        mb = p.stat().st_size / 1048576
        print(f"[fast_speak] Done -> {p}  ({mb:.2f} MB)")

    if args.play:
        print("[fast_speak] playing...")
        subprocess.run(["ffplay", "-autoexit", "-nodisp", "-loglevel", "error", str(outputs[0])])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
