#!/usr/bin/env python3
"""
index_speak.py — narrate text in Jason's cloned voice with IndexTTS-2.

Why IndexTTS-2: strong zero-shot cloning + accurate English pronunciation +
*built-in* long-form segmentation (no manual chunk-stitching like Zonos needed),
plus emotion control decoupled from the speaker.

Run with the IndexTTS venv:
  index-tts/.venv/bin/python scripts/index_speak.py \
      --file posts/ai-slop-youtube.md --out output/ai-slop-youtube_index.wav

Reference voice: a single clean clip works best (default: conversational).
Emotion (optional): --emotion neutral|happy|sad|angry (subtle by default).
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CKPT = ROOT / "index-tts" / "checkpoints"

# IndexTTS-2 emo_vector order: [happy, angry, sad, afraid, disgusted, melancholic, surprised, calm]
EMOTIONS = {
    "neutral": None,                                   # use the speaker prompt's own affect
    "happy":   [0.6, 0, 0, 0, 0, 0, 0, 0.2],
    "sad":     [0, 0, 0.6, 0, 0, 0.2, 0, 0.1],
    "angry":   [0, 0.6, 0, 0, 0.1, 0, 0, 0.1],
}


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"(\*\*|__|\*|_)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Narrate text in a cloned voice (IndexTTS-2).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", type=Path)
    src.add_argument("--text", type=str)
    ap.add_argument("--out", type=Path, default=Path("output/index_out.wav"))
    ap.add_argument("--ref", type=Path,
                    default=ROOT / "voice_samples" / "processed" / "conversational.wav",
                    help="Speaker reference clip (single clean clip is best).")
    ap.add_argument("--emotion", choices=list(EMOTIONS), default="neutral")
    ap.add_argument("--emo-alpha", type=float, default=0.8, help="Emotion intensity if not neutral.")
    ap.add_argument("--seg-tokens", type=int, default=120,
                    help="Max text tokens per internal segment (lower=safer, more seams).")
    ap.add_argument("--gap-ms", type=int, default=200, help="Silence between internal segments.")
    ap.add_argument("--fp16", action="store_true", help="Use fp16 (faster).")
    ap.add_argument("--format", choices=["wav", "ogg", "both"], default="wav",
                    help="Output format. 'ogg' = compressed Opus (~15-20x smaller).")
    ap.add_argument("--bitrate", default="48k", help="Opus bitrate for ogg (e.g. 32k, 48k, 64k).")
    ap.add_argument("--no-markdown", action="store_true")
    args = ap.parse_args()

    if not args.ref.exists():
        print(f"ERROR: reference clip not found: {args.ref}", file=sys.stderr)
        return 1

    raw = args.text if args.text is not None else args.file.read_text(encoding="utf-8")
    text = raw if args.no_markdown else strip_markdown(raw)
    if not text.strip():
        print("ERROR: nothing to speak.", file=sys.stderr)
        return 1

    print(f"[index_speak] {len(text)} chars. Loading IndexTTS-2...")
    from indextts.infer_v2 import IndexTTS2

    tts = IndexTTS2(
        cfg_path=str(CKPT / "config.yaml"),
        model_dir=str(CKPT),
        use_fp16=args.fp16,
        use_cuda_kernel=False,
        use_deepspeed=False,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # IndexTTS always writes a wav; we transcode to ogg afterward if requested.
    wav_path = args.out.with_suffix(".wav")
    emo_vector = EMOTIONS[args.emotion]
    tts.infer(
        spk_audio_prompt=str(args.ref),
        text=text,
        output_path=str(wav_path),
        emo_vector=emo_vector,
        emo_alpha=(1.0 if emo_vector is None else args.emo_alpha),
        use_random=False,
        interval_silence=args.gap_ms,
        max_text_tokens_per_segment=args.seg_tokens,
        verbose=False,
    )

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
        print(f"[index_speak] Done -> {p}  ({mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
