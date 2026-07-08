#!/usr/bin/env python3
"""
index_speak.py — narrate text in Jason's cloned voice with IndexTTS-2.

Why IndexTTS-2: strong zero-shot cloning + accurate English pronunciation +
*built-in* long-form segmentation (no manual chunk-stitching like Zonos needed),
plus emotion control decoupled from the speaker.

Run with the IndexTTS venv:
  index-tts/.venv/bin/python scripts/index_speak.py \
      --file posts/ai-slop-youtube.md --out output/ai-slop-youtube_index.wav

Reference voice: a single clean clip works best (default: presenter).
Emotion (optional): --emotion neutral|happy|sad|angry (subtle by default).
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_common import normalize_loudness, strip_markdown

# IndexTTS-2 internally truncates the speaker reference to 15s, so there's no
# point feeding it more. We pick which <=15s window to use via --ref-start/--ref-secs.
MAX_REF_SECS = 15.0
VOICE_DIRS = ("voice_samples", "voice_samples/processed")
AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".mp4", ".mov")

ROOT = Path(__file__).resolve().parent.parent
CKPT = ROOT / "index-tts" / "checkpoints"

# IndexTTS-2 emo_vector order: [happy, angry, sad, afraid, disgusted, melancholic, surprised, calm]
EMOTIONS = {
    "neutral": None,                                   # use the speaker prompt's own affect
    "happy":   [0.6, 0, 0, 0, 0, 0, 0, 0.2],
    "sad":     [0, 0, 0.6, 0, 0, 0.2, 0, 0.1],
    "angry":   [0, 0.6, 0, 0, 0.1, 0, 0, 0.1],
}


def list_voices():
    """All available reference voices (by name) under the voice dirs."""
    found = {}
    for d in VOICE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for f in sorted(base.iterdir()):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                found.setdefault(f.stem, f)  # first dir wins; processed is secondary
    return found


def resolve_ref(ref, voice):
    """Return a reference audio Path from an explicit --ref or a --voice name."""
    if ref:
        p = Path(ref)
        return p if p.exists() else None
    voices = list_voices()
    if voice:
        return voices.get(voice)
    return voices.get("presenter")  # default voice


def trim_ref(src: Path, start: float, secs):
    """Cut [start, start+secs] from src into a temp 24k mono wav. Returns its path."""
    tmp = Path(tempfile.mkdtemp(prefix="indexref_")) / "ref.wav"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if start and start > 0:
        cmd += ["-ss", str(start)]
    if secs:
        cmd += ["-t", str(secs)]
    cmd += ["-i", str(src), "-ac", "1", "-ar", "24000", str(tmp)]
    subprocess.run(cmd, check=True)
    return tmp


def main() -> int:
    ap = argparse.ArgumentParser(description="Narrate text in a cloned voice (IndexTTS-2).")
    src = ap.add_mutually_exclusive_group(required=False)
    src.add_argument("--file", type=Path)
    src.add_argument("--text", type=str)
    ap.add_argument("--out", type=Path, default=Path("output/index_out.wav"))
    ap.add_argument("--voice", help="Reference voice by name (see --list-voices). Default: presenter.")
    ap.add_argument("--ref", type=Path, help="Explicit reference clip path (overrides --voice).")
    ap.add_argument("--ref-start", type=float, default=0.0,
                    help="Seconds into the reference to start listening (e.g. skip an intro).")
    ap.add_argument("--ref-secs", type=float, default=None,
                    help=f"How many seconds of reference to use (max {MAX_REF_SECS:g}; model caps there).")
    ap.add_argument("--list-voices", action="store_true", help="List available reference voices and exit.")
    ap.add_argument("--emotion", choices=list(EMOTIONS), default="neutral")
    ap.add_argument("--emo-alpha", type=float, default=0.8, help="Emotion intensity if not neutral.")
    ap.add_argument("--seg-tokens", type=int, default=120,
                    help="Max text tokens per internal segment (lower=safer, more seams).")
    ap.add_argument("--gap-ms", type=int, default=200, help="Silence between internal segments.")
    ap.add_argument("--fp16", action="store_true", help="Use fp16 (faster).")
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
        voices = list_voices()
        print("Available reference voices:")
        for name, path in voices.items():
            print(f"  {name:28s} {path.relative_to(ROOT)}")
        return 0

    if args.text is None and args.file is None:
        print("ERROR: provide --text or --file (or --list-voices).", file=sys.stderr)
        return 1

    base_ref = resolve_ref(args.ref, args.voice)
    if base_ref is None:
        which = args.ref or args.voice or "presenter"
        print(f"ERROR: reference voice not found: {which}  (try --list-voices)", file=sys.stderr)
        return 1

    # Pick the requested window of the reference. Warn if asking for more than the
    # model will actually use.
    if args.ref_secs and args.ref_secs > MAX_REF_SECS:
        print(f"[index_speak] note: --ref-secs {args.ref_secs:g} exceeds the {MAX_REF_SECS:g}s "
              f"model cap; using {MAX_REF_SECS:g}s.")
        args.ref_secs = MAX_REF_SECS
    if args.ref_start > 0 or args.ref_secs:
        ref_path = trim_ref(base_ref, args.ref_start, args.ref_secs)
        win = f"{args.ref_start:g}s..{args.ref_start + (args.ref_secs or MAX_REF_SECS):g}s"
        print(f"[index_speak] reference: {base_ref.name} [{win}]")
    else:
        ref_path = base_ref
        print(f"[index_speak] reference: {base_ref.name} (first {MAX_REF_SECS:g}s)")

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
        spk_audio_prompt=str(ref_path),
        text=text,
        output_path=str(wav_path),
        emo_vector=emo_vector,
        emo_alpha=(1.0 if emo_vector is None else args.emo_alpha),
        use_random=False,
        interval_silence=args.gap_ms,
        max_text_tokens_per_segment=args.seg_tokens,
        verbose=False,
    )

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
        print(f"[index_speak] Done -> {p}  ({mb:.2f} MB)")

    if args.play:
        print("[index_speak] playing...")
        subprocess.run(["ffplay", "-autoexit", "-nodisp", "-loglevel", "error", str(outputs[0])])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
