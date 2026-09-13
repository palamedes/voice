#!/usr/bin/env python3
"""
index_speak.py — narrate text in Jason's cloned voice.

Two cloning engines behind the same pacing:
  --engine breeze (default)       Breeze TTS 2: runs in its own venv (breeze-tts/.venv), so
                                  this script re-launches itself there. It also needs the
                                  reference clip's exact words: they're transcribed once with
                                  Whisper into <voice>.txt beside the clip (edit that file if
                                  a word is wrong).
  --engine indextts / --indextts  IndexTTS-2: strong zero-shot cloning, accurate English
                                  pronunciation, emotion control decoupled from the speaker.

Pacing: by default (--auto-breaths) text is fed one sentence at a time with real
pauses between (longer at blank lines), and ,,, / [breath] / [pause N] marks add
breaks exactly where you want them. With --my-breaths ONLY those marks and line
breaks pause: no automatic pauses, and the model's own mid-phrase pauses are cut
down to 0.1 s. [voice-name] in the text switches voices until the next switch
(each voice's lines are levelled to the same loudness). --dry-run shows the plan.

Run with the IndexTTS venv:
  index-tts/.venv/bin/python scripts/index_speak.py \
      --file posts/ai-slop-youtube.md --out output/ai-slop-youtube_index.wav

Reference voice: a single clean clip works best (default: presenter).
Emotion (optional): --emotion neutral|happy|sad|angry (subtle by default).
"""
import argparse
import contextlib
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_common import normalize_loudness, pacing_plan, strip_markdown

# IndexTTS-2 internally truncates the speaker reference to 15s, so there's no
# point feeding it more. We pick which <=15s window to use via --ref-start/--ref-secs.
MAX_REF_SECS = 15.0
VOICE_DIRS = ("voice_samples", "voice_samples/processed")
AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".mp4", ".mov")

ROOT = Path(__file__).resolve().parent.parent
CKPT = ROOT / "index-tts" / "checkpoints"
BREEZE = ROOT / "breeze-tts"
ENGINES = {"indextts": "IndexTTS-2", "breeze": "Breeze TTS 2"}

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


def expand_voice_shorthand(argv):
    """Allow engine and voice names as bare flags: --breeze, --indextts, --calm, --muted, ...
    Rewrites them to --engine <name> / --voice <name> before argparse sees them."""
    voices = list_voices()
    out = []
    for a in argv:
        if a.startswith("--") and a[2:] in ENGINES:
            out += ["--engine", a[2:]]
        elif a.startswith("--") and a[2:] in voices:
            out += ["--voice", a[2:]]
        else:
            out.append(a)
    return out


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


def trim_edges(audio, sr, floor_db=-40, pad_ms=40):
    """Cut the model's own leading/trailing silence so the gaps we insert are exact.
    Quiet = 10 ms frames more than floor_db below the chunk's loudest frame."""
    hop = sr // 100
    n = len(audio) // hop
    if n == 0:
        return audio
    peaks = np.abs(audio[:n * hop].astype(np.int32)).reshape(n, hop).max(axis=1)
    loud = np.flatnonzero(peaks > peaks.max() * 10 ** (floor_db / 20))
    if not len(loud):
        return audio
    pad = sr * pad_ms // 1000
    return audio[max(0, loud[0] * hop - pad):min(len(audio), (loud[-1] + 1) * hop + pad)]


# With --my-breaths, the model's own pauses inside a chunk are cut down to this.
INNER_PAUSE_MS = 100


def tighten_pauses(audio, sr, max_ms=INNER_PAUSE_MS, floor_db=-40):
    """Shorten silences inside a chunk to max_ms, so the only real pauses are the ones
    we insert. Only near-silent audio is removed (same 'quiet' test as trim_edges)."""
    hop = sr // 100
    n = len(audio) // hop
    if n == 0:
        return audio
    peaks = np.abs(audio[:n * hop].astype(np.int32)).reshape(n, hop).max(axis=1)
    quiet = peaks <= peaks.max() * 10 ** (floor_db / 20)
    keep = np.ones(len(audio), dtype=bool)
    half = max_ms // 20                  # 10 ms frames kept on each side of a cut
    i = 0
    while i < n:
        j = i
        while j < n and quiet[j]:
            j += 1
        if j - i > 2 * half and i > 0 and j < n:   # interior quiet run longer than max_ms
            keep[(i + half) * hop:(j - half) * hop] = False
        i = j + 1
    return audio[keep]


def stretch(audio, sr, rate):
    """Change speaking rate without changing pitch (ffmpeg's rubberband filter)."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1",
         "-i", "-", "-af", f"rubberband=tempo={rate}", "-f", "s16le", "-"],
        input=audio.tobytes(), capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.int16)


def write_wav(path, audio, sr):
    """Write int16 mono samples to a wav file."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())


def read_wav(path):
    """int16 mono samples from a wav file (as written by write_wav)."""
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def speech_level_db(chunks, sr):
    """Loudness of the speech in these chunks, in dB: RMS over the 10 ms frames within
    40 dB of the loudest one, so pauses and silence don't count."""
    x = np.concatenate(chunks).astype(np.float64)
    hop = sr // 100
    n = len(x) // hop
    if n == 0:
        return 0.0
    frames = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    active = frames[frames > frames.max() * 10 ** (-40 / 20)]
    return float(20 * np.log10(np.sqrt((active ** 2).mean()) + 1e-9))


def assemble(rendered, sr, wav_path, normalize=True, lufs=-16.0, name=lambda v: v):
    """Join rendered chunks [(speech or None, pause_ms, voice), ...] and their pauses into
    wav_path, levelling every voice to the same loudness, then loudness-normalize the
    file. Shared by ./speak and Jarvis's render. Returns the length in seconds."""
    # Different reference clips come out at different loudness. Turn every voice down to
    # the quietest one's speech level (so nothing clips); the final normalization then
    # lifts the whole file.
    spoken = {}
    for speech, _, voice in rendered:
        if speech is not None:
            spoken.setdefault(voice, []).append(speech)
    if len(spoken) > 1:
        levels = {v: speech_level_db(chunks, sr) for v, chunks in spoken.items()}
        target = min(levels.values())
        print("[index_speak] levelled voices: " + ", ".join(
            f"{name(v)} {target - db:+.1f} dB" for v, db in levels.items()))
        rendered = [(s if s is None else (s * 10 ** ((target - levels[v]) / 20)).astype(np.int16), ms, v)
                    for s, ms, v in rendered]
    pieces, spans, pos = [], [], 0       # spans: where each voice's speech sits in the file
    for speech, pause_ms, voice in rendered:
        if speech is not None:
            pieces.append(speech)
            spans.append((pos, pos + len(speech), voice))
            pos += len(speech)
        pieces.append(np.zeros(sr * pause_ms // 1000, dtype=np.int16))
        pos += len(pieces[-1])
    audio = np.concatenate(pieces)
    write_wav(wav_path, audio, sr)

    if normalize:
        normalize_loudness(wav_path, target_i=lufs)
        if len(spoken) > 1:
            # loudnorm's time-varying gain nudges the levelled voices apart again: measure
            # each voice in the normalized file, correct the raw audio by the difference,
            # and normalize once more.
            done = read_wav(wav_path)
            after = {v: speech_level_db([done[a:b] for a, b, vv in spans if vv == v], sr)
                     for v in spoken}
            mean = sum(after.values()) / len(after)
            fixed = audio.astype(np.float64)
            for a, b, v in spans:
                fixed[a:b] *= 10 ** ((mean - after[v]) / 20)
            write_wav(wav_path, np.clip(fixed, -32768, 32767).astype(np.int16), sr)
            normalize_loudness(wav_path, target_i=lufs)
    return len(audio) / sr


@contextlib.contextmanager
def muted_output():
    """Silence stdout/stderr at the file-descriptor level, which also catches output from
    C extensions and subprocesses. Exceptions still surface once output is restored."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved = os.dup(1), os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        for fd in (*saved, devnull):
            os.close(fd)


def ref_transcript(clip: Path, sidecar=None):
    """The exact words spoken in the reference clip (Breeze TTS 2 needs them). Read from
    the sidecar .txt if there is one; otherwise transcribed with the cached Whisper model
    and saved to the sidecar, so each voice is only transcribed once."""
    if sidecar and sidecar.exists():
        return sidecar.read_text(encoding="utf-8").strip()
    print("[index_speak] transcribing the reference clip for Breeze (once per voice)...")
    import soundfile as sf
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor
    wav16 = Path(tempfile.mkdtemp(prefix="indexref_")) / "ref16k.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(clip),
                    "-ac", "1", "-ar", "16000", str(wav16)], check=True)
    audio, _ = sf.read(wav16, dtype="float32")
    name = "openai/whisper-large-v3-turbo"
    proc = WhisperProcessor.from_pretrained(name)
    model = WhisperForConditionalGeneration.from_pretrained(name, dtype=torch.float16).to("cuda")
    inputs = proc(audio, sampling_rate=16000, return_tensors="pt", return_attention_mask=True)
    with torch.no_grad():
        ids = model.generate(inputs.input_features.to("cuda", torch.float16),
                             attention_mask=inputs.attention_mask.to("cuda"),
                             language="en", task="transcribe")
    text = proc.batch_decode(ids, skip_special_tokens=True)[0].strip()
    del model
    torch.cuda.empty_cache()
    if sidecar:
        sidecar.write_text(text + "\n", encoding="utf-8")
        print(f"[index_speak] saved {sidecar.relative_to(ROOT)} (edit it if a word is wrong)")
    return text


def load_indextts(args, gap_ms):
    """IndexTTS-2 -> (render(text, ref_path, ref_text) -> int16 samples, sample rate).
    ref_text is ignored: IndexTTS doesn't need the reference clip's words."""
    from indextts.infer_v2 import IndexTTS2
    tts = IndexTTS2(cfg_path=str(CKPT / "config.yaml"), model_dir=str(CKPT), use_fp16=args.fp16,
                    use_cuda_kernel=False, use_deepspeed=False)
    emo_vector = EMOTIONS[args.emotion]

    def render(text, ref_path, ref_text=None):
        _, audio = tts.infer(
            spk_audio_prompt=str(ref_path),
            text=text,
            output_path=None,          # return (sr, int16 samples) instead of writing
            emo_vector=emo_vector,
            emo_alpha=(1.0 if emo_vector is None else args.emo_alpha),
            use_random=False,
            interval_silence=gap_ms,
            max_text_tokens_per_segment=args.seg_tokens,
            verbose=False,
        )
        return audio[:, 0]
    return render, 22050


def load_breeze(fast=False):
    """Breeze TTS 2 -> (render(text, ref_path, ref_text) -> int16 samples, sample rate).
    Needs breeze-tts/.venv.
    fast=True captures CUDA graphs up front: a slower start, then much less per-chunk overhead."""
    sys.path.insert(0, str(BREEZE))
    import functools
    from dataclasses import replace
    import breeze_infer.templates as templates
    from breeze_infer.runtime import (load_runtime, resolve_device, set_all_seeds,
                                      update_generation_config_for_breeze)
    from breeze_infer.templates import get_template, prepare_inputs, select_template_name
    from models.fast_streaming import FastBreezeStreamingRuntime, FastStreamingConfig
    from models.warmup_profile import load_warmup_profile

    # Its audio-tokenizer package nags about SoX and flash-attn on import (for a tokenizer
    # Breeze doesn't use), and model loading prints debug lines; keep all that quiet.
    with muted_output():
        tokenizer, model, audio_tokenizer = load_runtime(BREEZE / "breeze-tts-2", device=resolve_device(),
                                                         attn_implementation="eager")
    update_generation_config_for_breeze(model)
    # prepare_inputs re-encodes the reference clip for every chunk; encode each clip once per run.
    templates._encode_prompt_audio = functools.lru_cache(maxsize=None)(templates._encode_prompt_audio)

    # Breeze's own infer.py settings. With fast, only the per-frame stages (backbone decode,
    # depth decoder, codec) run as CUDA graphs: that loop is where the time goes. The text
    # encoder and prefill run once per chunk, so they stay eager, which also avoids their
    # prompt-length buckets (the stock ones stop short of a cloning prompt) and their memory.
    config = FastStreamingConfig(max_new_tokens=1500, max_seq_len=2048, repetition_penalty=1.1,
                                 fast_backbone_decode=fast, fast_depth_decoder=fast, fast_codec=fast)
    runtime = FastBreezeStreamingRuntime(model, audio_tokenizer, config, tokenizer=tokenizer)
    if runtime.fast_enabled:
        # Warm only the one-branch (CFG 1) graphs we use; unfrozen, anything else is
        # captured on first use instead of failing.
        profile = replace(load_warmup_profile(BREEZE / "configs" / "fast.json"),
                          cfg_scales=(1.0,), codec_chunk_frames=runtime.codec_chunk_frames,
                          freeze_after_warmup=False,
                          backbone_decode_branch_batch_sizes=(1,), depth_decoder_batch_sizes=(1,))
        t0 = time.time()
        with muted_output():
            runtime.warmup_from_profile(profile)
        print(f"[index_speak] Breeze fast path warmed up in {time.time() - t0:.1f}s")

    def render(text, ref_path, ref_text):
        request = {"id": "chunk", "text": text, "speaker": "S0",
                   "ref_audio_path": str(ref_path), "ref_text": ref_text}
        set_all_seeds(42)
        inputs = prepare_inputs(tokenizer, audio_tokenizer, model, [request],
                                get_template(select_template_name(request)),
                                guidance_scale=1.0, guidance_scale_ref=None, guidance_scale_ins=None)
        audio = np.concatenate([np.asarray(c.audio).reshape(-1)
                                for c in runtime.iter_audio_chunks(inputs, request_id="chunk", seed=42)])
        if audio.dtype.kind == "f":
            audio = np.clip(audio, -1, 1) * 32767
        return audio.astype(np.int16)
    return render, runtime.sample_rate


def main() -> int:
    ap = argparse.ArgumentParser(description="Narrate text in a cloned voice (IndexTTS-2 or Breeze TTS 2).")
    src = ap.add_mutually_exclusive_group(required=False)
    src.add_argument("--file", type=Path)
    src.add_argument("--text", type=str)
    ap.add_argument("words", nargs="*", help="The text to read, as plain words (instead of --text/--file).")
    ap.add_argument("--out", type=Path, default=Path("output/index_out.wav"))
    ap.add_argument("--engine", choices=list(ENGINES), default="breeze",
                    help="Cloning engine: breeze (Breeze TTS 2, default) or indextts (IndexTTS-2). "
                         "Bare --breeze / --indextts work too.")
    ap.add_argument("--fast", action=argparse.BooleanOptionalAction, default=None,
                    help="Breeze only, on by default: ~9 s of CUDA-graph warm-up, then roughly 5x faster "
                         "rendering. --no-fast uses Breeze's plain (eager) path.")
    ap.add_argument("--voice", help="Reference voice by name (see --list-voices). Any voice name "
                    "also works as a bare flag, e.g. --calm. Default: presenter.")
    ap.add_argument("--ref", type=Path, help="Explicit reference clip path (overrides --voice).")
    ap.add_argument("--ref-start", type=float, default=0.0,
                    help="Seconds into the reference to start listening (e.g. skip an intro).")
    ap.add_argument("--ref-secs", type=float, default=None,
                    help=f"How many seconds of reference to use (max {MAX_REF_SECS:g}; model caps there).")
    ap.add_argument("--list-voices", action="store_true", help="List available reference voices and exit.")
    ap.add_argument("--emotion", choices=list(EMOTIONS), default="neutral", help="(IndexTTS only)")
    ap.add_argument("--emo-alpha", type=float, default=0.8,
                    help="Emotion intensity if not neutral (IndexTTS only).")
    ap.add_argument("--sentence-gap", type=int, default=450, help="Silence after each sentence (ms).")
    ap.add_argument("--para-gap", type=int, default=900,
                    help="Silence after each paragraph, i.e. at a blank line (ms).")
    ap.add_argument("--breath-gap", type=int, default=400,
                    help="Silence at each ,,, or [breath] mark in the text (ms).")
    ap.add_argument("--rate", type=float, default=1.0,
                    help="Speaking rate, e.g. 0.9 = 10%% slower. Pitch is kept; pauses are not stretched.")
    breaths = ap.add_mutually_exclusive_group()
    breaths.add_argument("--auto-breaths", dest="auto_breaths", action="store_true", default=True,
                         help="Pause after every sentence and paragraph, plus at your marks (default).")
    breaths.add_argument("--my-breaths", dest="auto_breaths", action="store_false",
                         help="Pause ONLY at your ,,, / [breath] / [pause] marks and line breaks; read the "
                              "rest straight through (the model's own mid-phrase pauses are cut to 0.1 s).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print how the text will be chunked and paused, then exit (no model load).")
    ap.add_argument("--seg-tokens", type=int, default=120,
                    help="Max text tokens per internal segment (lower=safer, more seams; IndexTTS only).")
    ap.add_argument("--gap-ms", type=int, default=None,
                    help="Silence where IndexTTS itself splits an overlong chunk "
                         "(default 200 ms; 0 with --my-breaths; IndexTTS only).")
    ap.add_argument("--fp16", action="store_true", help="Use fp16 (faster; IndexTTS only).")
    ap.add_argument("--format", choices=["wav", "ogg", "both"], default="wav",
                    help="Output format. 'ogg' = compressed Opus (~15-20x smaller).")
    ap.add_argument("--bitrate", default="48k", help="Opus bitrate for ogg (e.g. 32k, 48k, 64k).")
    ap.add_argument("--play", action="store_true", help="Play the audio out loud (ffplay) after generating.")
    ap.add_argument("--normalize", action=argparse.BooleanOptionalAction, default=True,
                    help="Loudness-normalize output to a consistent level (default on).")
    ap.add_argument("--lufs", type=float, default=-16.0, help="Target integrated loudness (LUFS).")
    ap.add_argument("--no-markdown", action="store_true")
    # Intermixed, so plain words and flags (with or without values) can come in any order.
    args = ap.parse_intermixed_args(expand_voice_shorthand(sys.argv[1:]))
    if args.words:
        if args.text is not None or args.file is not None:
            ap.error("give the text as plain words or with --text/--file, not both")
        args.text = " ".join(args.words)

    if args.list_voices:
        voices = list_voices()
        print("Available reference voices:")
        for name, path in voices.items():
            print(f"  {name:28s} {path.relative_to(ROOT)}")
        return 0

    if args.text is None and args.file is None:
        print("ERROR: nothing to read: give the text as words, --text, or --file (or --list-voices).",
              file=sys.stderr)
        return 1

    breeze_py = BREEZE / ".venv" / "bin" / "python"
    if (args.engine == "breeze" and not args.dry_run
            and Path(sys.prefix).resolve() != breeze_py.parent.parent.resolve()):
        # Breeze needs its own environment (newer torch/transformers): re-launch there.
        if not breeze_py.exists():
            print(f"ERROR: Breeze TTS 2 isn't installed ({breeze_py} missing); see README Setup.",
                  file=sys.stderr)
            return 1
        os.execv(breeze_py, [str(breeze_py), str(Path(__file__).resolve()), *sys.argv[1:]])

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
    custom_window = args.ref_start > 0 or bool(args.ref_secs)
    if custom_window or args.engine == "breeze":
        # Breeze has no built-in 15 s cap, so it always gets an explicit window.
        ref_path = trim_ref(base_ref, args.ref_start, args.ref_secs or MAX_REF_SECS)
    else:
        ref_path = base_ref
    win = f"{args.ref_start:g}s..{args.ref_start + (args.ref_secs or MAX_REF_SECS):g}s"
    print(f"[index_speak] {ENGINES[args.engine]}, reference: {base_ref.name} [{win}]")
    # The default window's transcript is cached beside the clip; custom windows aren't.
    sidecar = None if custom_window else base_ref.with_suffix(".txt")

    raw = args.text if args.text is not None else args.file.read_text(encoding="utf-8")
    text = raw if args.no_markdown else strip_markdown(raw)
    if not text.strip():
        print("ERROR: nothing to speak.", file=sys.stderr)
        return 1

    # IndexTTS-2 on its own flattens paragraph breaks and packs several sentences
    # into one generation, so it rushes. Instead we feed it one sentence (or
    # [pause]-delimited phrase) at a time and insert our own silences. With
    # --my-breaths only the marks split the text and nothing else is added.
    all_voices = list_voices()
    plan = pacing_plan(text, sentence_ms=args.sentence_gap, para_ms=args.para_gap,
                       breath_ms=args.breath_gap, auto=args.auto_breaths, voices=set(all_voices))
    gap_ms = args.gap_ms if args.gap_ms is not None else (200 if args.auto_breaths else 0)
    start_name = args.voice or base_ref.stem
    if args.dry_run:
        switches = any(voice is not None for _, _, voice in plan)
        current = object()
        for chunk, pause_ms, voice in plan:
            if switches and voice != current:
                print(f"  == {voice or start_name} ==")
                current = voice
            print(f"  {chunk or '(silence)'}\n      ~ {pause_ms} ms")
        return 0

    # One reference per voice: the starting one (--voice/--ref, with its window) plus
    # each [name] switched to in the text, which uses its clip's first 15 s.
    refs = {None: (ref_path, sidecar)}
    for name in dict.fromkeys(voice for _, _, voice in plan if voice is not None):
        clip = all_voices[name]
        refs[name] = (trim_ref(clip, 0, MAX_REF_SECS) if args.engine == "breeze" else clip,
                      clip.with_suffix(".txt"))
    if len(refs) > 1:
        print(f"[index_speak] voices switched to in the text: {', '.join(n for n in refs if n)}")

    print(f"[index_speak] {len(text)} chars, {len(plan)} chunks. Loading {ENGINES[args.engine]}...")
    if args.engine == "breeze":
        if args.emotion != "neutral":
            print("[index_speak] note: --emotion only works with IndexTTS; ignored.")
        # Breeze needs each reference clip's words (saved beside the clip after the first time).
        refs = {v: (path, ref_transcript(path, side)) for v, (path, side) in refs.items()}
        # --fast is on unless --no-fast was given.
        render, sr = load_breeze(fast=args.fast is not False)
    else:
        if args.fast:
            print("[index_speak] note: --fast only applies to Breeze; ignored.")
        refs = {v: (path, None) for v, (path, _) in refs.items()}
        render, sr = load_indextts(args, gap_ms)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # We always write a wav; it's transcoded to ogg afterward if requested.
    wav_path = args.out.with_suffix(".wav")

    gen_start = time.time()
    rendered = []                        # (speech or None, pause_ms, voice)
    for i, (chunk, pause_ms, voice) in enumerate(plan, 1):
        speech = None
        if chunk:
            who = f" [{voice}]" if voice else ""
            print(f"[index_speak] chunk {i}/{len(plan)}{who}: {chunk[:70]}")
            speech = trim_edges(render(chunk, *refs[voice]), sr)
            if not args.auto_breaths:
                speech = tighten_pauses(speech, sr)
            if args.rate != 1.0:
                speech = stretch(speech, sr, args.rate)
        rendered.append((speech, pause_ms, voice))

    seconds = assemble(rendered, sr, wav_path, normalize=args.normalize, lufs=args.lufs,
                       name=lambda v: v or start_name)
    print(f"[index_speak] {seconds:.1f}s of audio in {time.time() - gen_start:.1f}s")

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
