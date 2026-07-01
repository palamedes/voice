#!/usr/bin/env python3
"""
merge_audio.py — merge two audio clips into one, with a natural pause at the seam.

Trims whatever silence already exists at the join (trailing silence of clip A,
leading silence of clip B) and inserts one consistent, configurable gap instead
- otherwise you'd stack pre-existing silence with the inserted gap, or in the
worst case get an abrupt cut if a clip was trimmed tight. Also reconciles
sample rate/channels if the two clips came from different engines.

Pure ffmpeg + stdlib, no ML deps - run with plain system python3:
  python3 scripts/merge_audio.py output/intro.wav output/body.wav --out output/combined.wav
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_common import normalize_loudness

# Trim silence beyond this level at the very start/end of each clip before
# inserting the gap, so pre-existing silence doesn't stack with it.
SILENCE_THRESHOLD_DB = "-45dB"
SILENCE_MIN_DURATION = 0.05  # seconds


def probe(path: Path):
    """Return (sample_rate, channels) of an audio file."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=sample_rate,channels", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True).stdout.split()
    return int(out[0]), int(out[1])


def trim_silence(src: Path, dst: Path, sr: int, channels: int):
    """Strip existing leading/trailing silence and conform to (sr, channels).

    Only trims the two true edges, not internal pauses: a naive single
    silenceremove pass with both start_periods and stop_periods set stops at
    the FIRST silence run past the threshold (e.g. a mid-sentence pause),
    chopping off real speech after it. Trimming the start, then reversing and
    trimming the (now-leading) end, then reversing back avoids that.
    """
    edge = (f"silenceremove=start_periods=1:start_threshold={SILENCE_THRESHOLD_DB}:"
            f"start_silence={SILENCE_MIN_DURATION}")
    flt = f"{edge},areverse,{edge},areverse"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
         "-af", flt, "-ar", str(sr), "-ac", str(channels), str(dst)],
        check=True)


def make_silence(dst: Path, sr: int, channels: int, ms: int):
    layout = "mono" if channels == 1 else "stereo"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"anullsrc=r={sr}:cl={layout}",
         "-t", str(ms / 1000), "-ar", str(sr), "-ac", str(channels), str(dst)],
        check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge two audio clips with a natural pause at the seam.")
    ap.add_argument("clip_a", type=Path)
    ap.add_argument("clip_b", type=Path)
    ap.add_argument("--out", type=Path, default=Path("output/merged.wav"))
    ap.add_argument("--gap-ms", type=int, default=450,
                    help="Silence inserted at the seam (default: a natural sentence-to-sentence "
                         "pause). Use ~700+ for a paragraph break, less for a mid-sentence join.")
    ap.add_argument("--format", choices=["wav", "ogg", "both"], default="wav",
                    help="Output format. 'ogg' = compressed Opus (~15-20x smaller).")
    ap.add_argument("--bitrate", default="48k", help="Opus bitrate for ogg (e.g. 32k, 48k, 64k).")
    ap.add_argument("--normalize", action=argparse.BooleanOptionalAction, default=True,
                    help="Loudness-normalize the merged result (default on).")
    ap.add_argument("--lufs", type=float, default=-16.0, help="Target integrated loudness (LUFS).")
    args = ap.parse_args()

    for clip in (args.clip_a, args.clip_b):
        if not clip.exists():
            print(f"ERROR: not found: {clip}", file=sys.stderr)
            return 1

    sr, channels = probe(args.clip_a)
    print(f"[merge_audio] target format: {sr} Hz, {channels}ch (from {args.clip_a.name})")

    tmp = Path(tempfile.mkdtemp(prefix="mergeaudio_"))
    trimmed_a, trimmed_b, silence = tmp / "a.wav", tmp / "b.wav", tmp / "silence.wav"
    trim_silence(args.clip_a, trimmed_a, sr, channels)
    trim_silence(args.clip_b, trimmed_b, sr, channels)
    make_silence(silence, sr, channels, args.gap_ms)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    wav_path = args.out.with_suffix(".wav")
    filelist = tmp / "concat.txt"
    filelist.write_text("".join(f"file '{p}'\n" for p in (trimmed_a, silence, trimmed_b)))
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(filelist), "-c", "copy", str(wav_path)],
        check=True)

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
            wav_path.unlink()
            outputs = [ogg_path]

    for p in outputs:
        mb = p.stat().st_size / 1048576
        print(f"[merge_audio] Done -> {p}  ({mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
