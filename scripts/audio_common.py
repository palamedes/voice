"""Shared helpers for the narration scripts (index_speak.py, fast_speak.py)."""
import json
import re
import subprocess
import sys
from pathlib import Path


def normalize_loudness(path: Path, target_i: float = -16.0, tp: float = -1.5, lra: float = 11.0):
    """Two-pass EBU R128 loudness normalization to a fixed target, in place.

    Different reference clips/voices produce very different output volumes; this
    makes every render land at the same perceived loudness (broadcast/podcast standard).
    """
    # Preserve the sample rate (loudnorm otherwise emits 192kHz).
    sr = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=sample_rate", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True).stdout.strip() or "44100"
    # Pass 1: measure.
    p1 = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
         f"loudnorm=I={target_i}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\".*?\}", p1.stderr, re.DOTALL)
    if not m:
        print("[audio_common] loudness measure failed; leaving volume as-is.", file=sys.stderr)
        return
    d = json.loads(m.group(0))
    # Pass 2: apply with measured values.
    flt = (f"loudnorm=I={target_i}:TP={tp}:LRA={lra}:"
           f"measured_I={d['input_i']}:measured_TP={d['input_tp']}:"
           f"measured_LRA={d['input_lra']}:measured_thresh={d['input_thresh']}:"
           f"offset={d['target_offset']}:linear=false")
    tmp = path.with_suffix(".norm.wav")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
         "-af", flt, "-ar", sr, str(tmp)], check=True)
    tmp.replace(path)


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
