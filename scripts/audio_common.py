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


# Inline marks: ,,, (breathe here), [breath], [pause], [pause 1.5], [pause 1.5s], [pause 800ms].
# ,,, must be caught before IndexTTS sees it — its normalizer turns it into "…".
MARK = re.compile(r"\[(pause|breath)(?:\s+(\d+(?:\.\d+)?)\s*(ms|s)?)?\]|[ \t]*,{3,}", re.IGNORECASE)
# With --my-breaths every line break is a breath mark too.
MARK_OR_BREAK = re.compile(MARK.pattern + r"|\n", re.IGNORECASE)
# Sentence boundary: whitespace after . ! ? or …, optionally behind a closing quote/paren.
SENTENCE_END = re.compile(r"(?:(?<=[.!?…])|(?<=[.!?…][\"'”’)]))\s+")
# Words whose trailing period isn't a sentence end ("Dr. Smith", "e.g. this").
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "e.g", "i.e"}


def split_sentences(text: str) -> list:
    out = []
    for piece in SENTENCE_END.split(text.strip()):
        if not piece:
            continue
        last = out[-1].split()[-1].rstrip(".").lower() if out else ""
        if out and (last in ABBREVIATIONS or (len(last) == 1 and last.isalpha())):
            out[-1] += " " + piece       # "Dr." / "J." — not a real sentence end
        else:
            out.append(piece)
    return out


def pacing_plan(text: str, sentence_ms=450, para_ms=900, pause_ms=700, breath_ms=400,
                auto=True) -> list:
    """Split text into [(chunk, pause_after_ms), ...] for one-chunk-at-a-time synthesis.

    Every sentence becomes its own chunk followed by sentence_ms of silence; the
    last chunk of a paragraph (blank-line separated) gets para_ms instead. An
    inline ,,, / [breath] / [pause N] mark also ends a chunk, and its length
    replaces the automatic gap there (back-to-back marks add up). A chunk may be
    "" when a mark comes before any text (leading silence).

    With auto=False only the marks and line breaks break the text, and there are
    no sentence or paragraph pauses. Every line break is a breath (breath_ms), so
    blank lines stack: one break = 1 breath, an empty line between = 2, and so on.
    A mark at the end of a line stands in for that line's first break.
    """
    plan = []            # entries: [chunk, pause_ms, explicit]
    split = split_sentences if auto else (lambda s: [" ".join(s.split())])

    def add_text(s):
        # Skip punctuation-only leftovers, e.g. the "." in "word [pause]."
        plan.extend([c, sentence_ms, False] for c in split(s) if re.search(r"\w", c))

    def add_mark(ms):
        if plan and plan[-1][2]:
            plan[-1][1] += ms            # stacked marks add up
        elif plan and plan[-1][0]:
            plan[-1][1:] = [ms, True]    # mark replaces the automatic gap
        else:
            plan.append(["", ms, True])

    # Auto: blank-line paragraphs, each ending in para_ms (single newlines are just
    # spaces). Mine: one block in which each line break is itself a breath mark.
    blocks, marks = (re.split(r"\n\s*\n", text), MARK) if auto else ([text.strip()], MARK_OR_BREAK)
    for para in blocks:
        if auto:
            para = " ".join(para.split())
        if not para:
            continue
        pos = 0
        line_ends_in_mark = False
        for m in marks.finditer(para):
            if re.search(r"\w", para[pos:m.start()]):
                line_ends_in_mark = False
            add_text(para[pos:m.start()])
            pos = m.end()
            if m.group(0) == "\n":
                if line_ends_in_mark:
                    line_ends_in_mark = False    # that mark is this line break's breath
                else:
                    add_mark(breath_ms)
                continue
            kind, num, unit = (m.group(1) or "breath").lower(), m.group(2), (m.group(3) or "s").lower()
            if num is None:
                add_mark(pause_ms if kind == "pause" else breath_ms)
            else:
                add_mark(round(float(num) * (1 if unit == "ms" else 1000)))
            line_ends_in_mark = True
        add_text(para[pos:])
        if plan and not plan[-1][2]:
            plan[-1][1] = para_ms
    if plan and not plan[-1][2]:
        plan[-1][1] = 0                  # no automatic gap after the very end
    return [(chunk, ms) for chunk, ms, _ in plan]


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"(\*\*|__|\*|_)", "", text)
    # Blank-line runs are left alone: with --my-breaths each line break is a breath.
    return text.strip()
