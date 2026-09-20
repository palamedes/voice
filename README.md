# voice

Turn a blog post into audio of *you* reading it out loud. Give it text and a
10–15 second clip of your voice; it gives you back a clean audio file in your
voice. Runs entirely locally on an NVIDIA GPU — nothing is uploaded anywhere.

Two engines, both cloning your voice:

- **[Breeze TTS 2](https://huggingface.co/BreezeBlue/Breeze-TTS-2)** — sounds
  like you, and can laugh, sigh or clear its throat on cue. The default.
  Renders in well under real time after a ~9 s warm-up. Non-commercial license.
- **[IndexTTS-2](https://github.com/index-tts/index-tts)** — also sounds like
  you, with its own delivery and emotion presets. Add `--indextts` to `./speak`
  or `./say`.

Only clone your own voice, or someone who has explicitly said yes.

## The commands

```sh
./speak "Hello, this is me."          # cloned voice → saved to output/
./say "Hello, this is me."            # cloned voice → out loud, nothing saved
./jarvis "Hello, this is me."         # cloned voice, always loaded → out loud in a second or two
./jarvis-ui                           # a local web page for Jarvis: voices, a panel, conversations, articles
```

They also exist as slash commands in a Claude Code session in this folder
(`/speak`, `/say`, `/jarvis`, plus `/merge`), and as fish functions so the
bare names work without `./`.

## Cheat sheet: everything you can write in the text

| Write | What it does | Engine |
|---|---|---|
| `,,,` or `[breath]` | a breath: 0.4 s pause (`--breath-gap` changes it) | both |
| `[pause]` | a 0.7 s pause | both |
| `[pause 2]`, `[pause 1.5s]`, `[pause 800ms]` | a pause of exactly that length | both |
| a blank line | a 0.9 s paragraph pause (`--para-gap` changes it) | both |
| a line break, with `--my-breaths` | a breath at every line break; each empty line adds another | both |
| `[art-bell]`, `[jason-ellis-presenter]`, … | reads what follows in that voice, until the next switch — [details](#switch-voices-mid-text-conversations) | both |
| `(sighs)`, `(laughs)`, `(clears throat)`, … | performs the sound — [full list below](#breeze-sounds-the-full-list) | Breeze |
| `(whispers)`, `(shouts)` | says what follows quietly / loudly | Breeze |
| Markdown (`#` headings, `**bold**`, links, code blocks, `---` rules, front matter) | stripped before reading | both |

A mark replaces the automatic pause at that spot, and back-to-back marks add
up. Everything else — voice, engine, speed, pause lengths, output format — is a
flag; see the [options reference](#options-reference).

## Two cloned engines

`./speak` and `./say` use Breeze TTS 2 unless you add `--indextts`:

```sh
./speak "Same words, Breeze TTS 2."                # default
./speak --indextts "Same words, IndexTTS-2."
./say --my-breaths --file posts/my-post.md
```

Everything else — voices, `,,,` / `[pause]` marks, `--my-breaths`, `--rate`,
`--dry-run`, formats — works the same on both. `--emotion`, `--fp16`,
`--seg-tokens` and `--gap-ms` are IndexTTS-only. The long form is
`--engine breeze` / `--engine indextts`.

Breeze renders in "fast" mode by default: it spends about 9 s up front
recording the GPU work for its per-frame loop, then renders roughly 5x faster
than its plain mode — a 38-second excerpt took 14 s instead of 77 s, and a
5-minute post takes a couple of minutes instead of ten. It's the same model and
voice; only how the GPU work is scheduled changes. `--no-fast` switches to the
plain mode, e.g. to compare if a render ever sounds off.

Breeze needs the exact words of the reference clip. The first time you use a
voice with it, Whisper transcribes the clip and saves the words next to it
(e.g. `voice_samples/processed/presenter.txt`); if Whisper got a word wrong,
fix the file.

### Breeze sounds: the full list

Write a sound in parentheses and Breeze performs it, in the voice you're using:

```sh
./speak "So they moved the goalposts again. (sighs) Of course they did."
./speak "(clears throat) Let's begin."
./speak "And that, apparently, was the plan. (chuckles)"
./speak "(whispers) Don't tell anyone I said this."
```

These are the 34 tags from Breeze's documentation, spelled exactly as it
expects them:

| Kind | Tags |
|---|---|
| Laughter | `(laughs)` `(chuckles)` `(giggles)` |
| Crying and pain | `(crying)` `(sobs)` `(whimpers)` `(groans)` `(moans)` |
| Breathing | `(sighs)` `(gasps)` `(inhales)` `(exhales)` `(breathing heavily)` |
| Delivery | `(whispers)` `(shouts)` `(screams)` `(singing)` `(humming)` `(stutters)` `(pause)` |
| Throat and nose | `(clears throat)` `(coughs)` `(sniffs)` |
| Mouth | `(smacks lips)` `(clicks tongue)` |
| Body | `(yawns)` `(sneezes)` `(hiccups)` `(burps)` `(gulps)` `(gags)` |
| Reactions | `(grunts)` `(scoffs)` `(snorts)` |

Things to know:

- The model's own README uses plain forms — `(laugh)`, `(sigh)`, `(cough)`,
  `(clears throat)` — and those work too. The table above comes from
  BreezeBlue's docs for its hosted model, which uses the "-s" spellings.
- Tested on this setup, Breeze recognized all of them (none was ever read out
  as a word), and by ear most of them work — some sound good, some come out
  funny, a few are bad. Try a sound on a line by itself before relying on it in
  a post. `(singing)` and `(humming)` run long (4–8 seconds).
- `(whispers)` and `(shouts)` change how the *following* words are said
  (noticeably quieter / louder) rather than adding a noise.
- `(pause)` is Breeze's own pause with no fixed length; for exact timing use
  `[pause 1.5]` instead.
- Because anything in parentheses may be taken as a sound, keep ordinary asides
  out of parentheses when using Breeze. (IndexTTS just reads them as text.)

## Jarvis: your cloned voice, always ready

`./speak` and `./say` load Breeze from scratch every time, so the first word
takes ~25 s. `./jarvis` keeps Breeze loaded in a background server instead:
start it once, and from then on each line starts playing a second or two after
you send it, streaming sentence by sentence (the next one renders while the
current one plays).

```sh
./jarvis                               # start the server; returns once it's ready (~25 s)
./jarvis "Good evening, sir."          # speak (starts the server first if needed)
./jarvis --art-bell                    # switch voice; it sticks for later lines
./jarvis --art-bell "Hello, caller."   # switch and speak
./jarvis "Actually, cancel that."      # a new line interrupts the current one
./jarvis --queue "And another thing."  # ...or waits its turn
./jarvis --stop                        # just stop talking
./jarvis --status                      # is it up, and in which voice?
./jarvis --quit                        # shut it down and free the GPU memory
```

Everything you can write in the text works here too (`,,,`, `[pause 1]`,
`(sighs)`, `[voice]` switches), plus `--my-breaths` and `--wait`. Voices are
levelled so they all play at about the same volume. The server stays up until
`--quit` and holds about 8 GB of GPU memory while it runs, so quit it before a
big `./speak` render or anything else GPU-heavy. It listens on
`/tmp/jarvis.sock` (log: `/tmp/jarvis.log`).

### The Jarvis page: a panel of voices and conversations

`./jarvis-ui` starts Jarvis (unless it's already running) and opens a small
local web page for it (`http://127.0.0.1:8765`), handy for giving each
character in a story or a D&D session its own voice:

- **Header:** Jarvis's status, plus Start, Stop talking and Shut down. Esc
  also stops talking. **Shut down** stops everything: Jarvis lets go of the
  GPU and the page's server exits, handing your terminal back; run
  `./jarvis-ui` to start again. (Start is there in case Jarvis failed or was
  quit from the command line.) The two buttons on the right switch between the
  **Panel + Conversation** view (described here) and the **Article** view
  (below).
- **Voices:** every voice in `voice_samples/`, folded by person — one line per
  name (`dennis-prager-1` and `-2` become **Dennis Prager**, 2 inside), which
  you open, close, and 📌 pin to the top of the list. Click a voice to add it to
  the panel (or, in the Article view, to read the article); drop new clips into
  `voice_samples/` and press Reload. A blue dot means that clip isn't in the
  repo yet — right-click it (or the person) to commit the clip and its
  transcript. Committing doesn't push.
- **Panel:** one card per speaker. Rename it ("Grukk the Orc"), type a line,
  press Enter, and Jarvis says it in that voice. **→** (or Ctrl+Enter) puts the
  line into the conversation instead, without changing the left and right
  speakers: someone who isn't one of them shows up as a green bubble, so a
  third or fourth character can chime in. L / R put that speaker on the left or
  right of the conversation.
- **Conversation:** iMessage-style bubbles between a left and a right voice.
  Type a line and press Enter: it's added and the side flips, so a
  back-and-forth is just typing (Tab switches side by hand). Click a line to
  fix a typo (Enter saves, Esc cancels). Hover a line for ▶ play, ⇄ move to
  the other side, ↑ ↓ and × delete, or drag it by ⠿ to reorder. **Play all**
  reads the whole exchange with the voice switches and the beats between
  speakers; **Copy as script** gives you the `[voice]`-marked text to render
  to a file with `./speak --file` (quit Jarvis first, since both need the GPU).
  **⬇ Render out** saves the whole conversation as a `.wav` in `output/`,
  named after it: the running Jarvis renders it with the same pacing, voice
  levelling and loudness as `./speak` (in roughly 40% of the audio's length),
  and the page shows the path it wrote. An earlier render of the same name is
  never overwritten — the new one gets `-2`, `-3` and so on. While it renders,
  the page waits behind a box showing how far along it is and about how long is
  left; **Cancel** stops the render.
  "Speak each line as I add it" is off by default.
- **Nothing on the page interrupts:** a line you send while Jarvis is talking
  waits its turn and plays after a short beat, so you can type as fast as you
  like. Stop talking (or Esc) cuts it off and clears anything waiting.
- **Saved conversations** (for prepping scenes): **Save** (Ctrl+S) names the
  conversation and stores it, with its left/right speakers and the
  characters' names, as a file in `conversations/`. Saved ones sit as chips at
  the top of the conversation: click one to load it (any missing characters
  come back onto the panel), ▶ to load and play it right away, × to delete it.
  **New** starts an empty one. A • next to the name means unsaved changes.
- Nothing is saved as audio files; it all streams straight to the speakers.
  The panel and the current conversation are also remembered in the browser.

Saved conversations are plain JSON, so you can also write scenes ahead of time
in an editor — drop a file like this into `conversations/` and it shows up as
a chip (guest lines name their own voice; left/right lines use whoever is on
that side):

```json
{
 "name": "The Rusty Tankard",
 "left": "orc",
 "right": "bard",
 "cast": [{"voice": "orc", "label": "Grukk the Orc"}, {"voice": "bard", "label": "Lyra"}],
 "lines": [
  {"side": "left", "text": "(grunts) You. Bard. Play something that isn't terrible."},
  {"side": "right", "text": "For you? Anything."},
  {"side": "guest", "voice": "presenter", "text": "The barkeep sighs and reaches for the club."}
 ]
}
```

#### The Article view: tune how an article reads, live

**Article** (top right) swaps the panel and conversation for an editor. You can
have several articles open at once: each is a tab along the top, **＋** starts
another, **Open ▾** reopens one you've closed, and **×** closes a tab without
deleting anything. Every open article is also a file in `articles/`, written as
you type, so they survive a cleared browser; **Delete** removes the article and
its file. Name it in the box on the left of the toolbar — that name is the tab's
label and what Save post and Render out call their files (renaming changes the
name inside the file, not the file itself).

Paste an article and it splits into paragraphs at the blank lines (if the text
has no blank lines at all, each line becomes a paragraph). Markdown is fine: headings,
links and emphasis are read as plain text; `---` rules, front matter and code
blocks are skipped. Pick who reads it by clicking a voice in the voices list (a ✓
marks the reader; **Read by** does the same), and press **▶ Read**: Jarvis
reads one paragraph at a time,
highlighting the one it's on and following it down the page.

Paragraphs go to Jarvis one at a time, so you can work on the ones further down
while it reads (add a `,,,`, a `[pause 1]`, a `(sighs)`, reword a sentence) and
it reads your new version when it gets there. To keep the reading flowing, the
next paragraph is sent a few seconds before the current one ends (it's marked
**up next**), so it follows after a normal paragraph pause, the same pause as
`./speak` and Render out. From then on, an edit to that paragraph waits for
⟳. To hear a change right away, hover the paragraph and press ⟳ (or
Ctrl+Enter while typing in it) to play just that one; ▶ reads on from there.
While it's reading, either one goes next instead of cutting anything off.

- **⏸ Pause after ¶N** stops after paragraph N (the one up next, if it's
  already been sent); **■ Stop** (or Esc) stops right away. **▶ Read from ¶N**
  picks up where you left off (the ▸ mark); ⟲ top starts over.
- **Enter** starts a new paragraph at the caret (at the very start of one, a
  new empty paragraph above it); **Alt+Enter** adds an empty paragraph right
  below, wherever the caret is; **Shift+Enter** is a line break inside the
  paragraph (with only my breaths, a breath); **Backspace** at the very start of
  a paragraph joins it onto the end of the one above. Emptying a paragraph
  removes it.
  **Edit as text** shows the whole article in one box for big changes.
- **One paragraph in another voice:** hover it and click the name under ¶N on
  the left, then pick a voice ("Article reader" undoes it). It applies to that
  paragraph only, and the name stays showing in green. Copy text and Render out
  carry it as a `[voice]` switch, so `./speak` reads it the same way. A
  `[voice]` switch typed into the text carries on into the following paragraphs
  until the next switch, as it does in `./speak`. (Edit as text shows only the
  words: a paragraph you change there goes back to the article's reader.)
- **Only my breaths** is `--my-breaths`. **Pace** reads faster or slower (0.7×
  to 1.3×) without changing the voice's pitch, and your pauses keep the length
  you gave them — the same as `./speak --rate`. Click the number to go back to
  1.00×. It applies to reading and to Render out.
- **💾 Save post** writes the article to `posts/` as Markdown — the same text
  Copy text gives you, named after the article. Saving again updates that same
  file (it says "Updated"); renaming the article starts a new one. The page
  shows the path, and from there `./speak --file posts/…md` renders it without
  the page. (The article itself lives in `articles/` and saves as you type;
  `posts/` is the readable copy for everything outside the page.)
- **Copy text** copies the article, marks and all, to paste back into the post;
  **⬇ Render out** saves the whole article as a `.wav` in `output/`, read the
  same way, and tells you the path. To render just part of it, type the
  paragraphs in the box beside it — `29-45`, `1-10`, `10-` (to the end), `-10`
  (from the start) or `7` (just that one); blank means all, and Enter in the
  box starts the render. The file gets the range in its name
  (`field-notes-p29-45.wav`), and it opens in whichever voice is reading at
  that paragraph.
- Reading carries on in the tab it started in, so you can work on another
  article while one is being read; that tab is marked ▶. Only one can be read
  at a time.

The page only listens on 127.0.0.1 and only takes requests from itself.
Ctrl+C in the terminal works like Shut down: it stops the page and Jarvis
(closing the terminal does too). `./jarvis-ui --keep-jarvis` leaves Jarvis
running when the page stops, for `./jarvis` from the command line;
`--no-start` opens the page without starting Jarvis; `--port` and `--no-open`
do what they say.

## Voices

### List the available voices

```sh
./speak --list-voices
```

A "voice" is just an audio file in `voice_samples/` or
`voice_samples/processed/` — its name is the filename without the extension.
The default is `presenter`.

### Use a voice

Any listed voice name works as a bare flag, or via `--voice`:

```sh
./speak --calm "Same me, calmer read."
./speak --voice muted --file posts/my-post.md
```

### Switch voices mid-text (conversations)

Put a voice's name in square brackets and everything after it is read in that
voice, until the next switch:

```
[jason-ellis-presenter] So I asked the obvious question.
[art-bell] Somewhere over the high desert, the night is dark...
And this line is still Art Bell.
[jason-ellis-presenter] ,,, and that's where it gets weird.
```

- Use the exact names from `./speak --list-voices`. Text before the first
  switch uses `--voice` (default `presenter`).
- Speakers can share a line: `[art-bell] Go ahead, caller. [jason-ellis-ambiki]
  Hi Art.` works just as well as one speaker per line.
- A change of speaker always gets a beat: the normal sentence pause in the
  default mode, or a 0.4 s breath with `--my-breaths`. Your own `,,,` or
  `[pause]` at that spot replaces it (`[pause 0]` for none).
- Each voice is levelled to the same average loudness (within about 2 dB in
  testing). Individual lines still vary a little, the same as with one voice,
  and a `(whispers)` line stays quiet.
- Switched-to voices use the first 15 s of their clip; `--ref-start` /
  `--ref-secs` only apply to the starting voice.
- A bracketed word that isn't a voice name (a typo, or a real `[sic]`) stays in
  the text and you get a warning. `--dry-run` shows who reads what.
- Works with both engines. With Breeze, a voice's first use also transcribes
  its clip (see [Two cloned engines](#two-cloned-engines)).

### Add a new voice

1. Record (or find) 10–15 seconds of the person talking naturally. One voice,
   no music, no background noise, ending on a natural pause. Any format works
   as a source — wav, mp3, even an mp4 video.
2. Clean it into a reference clip:

   ```sh
   scripts/prep_ref.sh SOURCE.mp4 0 12 voice_samples/processed/myvoice.wav
   #                   input      │ │  output — filename becomes the voice name
   #                        start ┘ └ seconds to keep
   ```

3. Use it:

   ```sh
   ./speak --myvoice "Hello from the new voice."
   ```

The clip is the *entire* training step — there is no fine-tuning, and the only
transcript is the one Breeze makes for itself. If a voice sounds off, fix the
clip: re-record, or slice a better
window from the source with different start/duration values. The model
ignores everything past 15 seconds, so longer is never better.

### What's the difference between `voice_samples/` and `voice_samples/processed/`?

- `voice_samples/` — raw source recordings, kept as-is (any format).
- `voice_samples/processed/` — cleaned reference clips made by
  `prep_ref.sh`: trimmed, mono, 24 kHz, loudness-normalized, noise-reduced.

Both folders show up in `--list-voices` and both work, but processed clips
sound better because the model gets a clean, consistent input. Convention:
keep the raw recording in `voice_samples/`, put the cleaned clip you actually
speak with in `processed/` under a short name (`calm`, `muted`, `presenter`).

## Common tasks

```sh
# Read a whole post, save the audio
./speak --file posts/my-post.md --out output/my-post.wav

# Also write a compressed .ogg for embedding in a blog (~15-20x smaller;
# a 3.5-minute post ≈ 1 MB)
./speak --file posts/my-post.md --out output/my-post.wav --format both

# Use a specific 15-second window of a reference (skip a 30s intro, take 12s)
./speak --voice ryan-reynolds --ref-start 30 --ref-secs 12 --text "..."

# Join two clips with a natural pause at the seam (works across engines/formats)
./merge output/intro.wav output/body.wav --out output/combined.wav

# Play anything back
ffplay -autoexit -nodisp output/my-post.wav
```

Input can be `--text "..."` or `--file post.md`; markdown is stripped
automatically. Output is loudness-normalized to -16 LUFS (podcast standard)
so every clip comes out at the same volume.

## Pacing: pauses and breaths

The cloned voice reads one sentence at a time, with a real pause after each
(0.45 s) and a longer one at each blank line between paragraphs (0.9 s). To
control exactly where it breathes, mark it up in the text:

```
I built it in a weekend,,, then it broke.     ,,,  breathe here (0.4 s)
That was the end. [pause 2] Or so I thought.  [pause 2]  2 seconds; also 1.5s, 800ms
Wait for it [pause] there it is.              [pause]  0.7 s
```

A mark replaces the automatic pause at that spot; back-to-back marks add up.
Check where the breaks will fall before a long render with `--dry-run` (it
prints the chunks and pauses without loading the model).

```sh
./speak --file posts/my-post.md --dry-run          # preview the breaks
./speak --rate=0.9 "Ten percent slower, same pitch."
./speak --file posts/my-post.md --sentence-gap 600 --para-gap 1200 --breath-gap 400
```

### Your breaths only

By default the sentence and paragraph pauses are automatic, with your marks on
top. To pause *only* where you put a mark, add `--my-breaths`: no automatic
pauses at all, and each stretch between marks is read straight through in one
go. `--auto-breaths` (the default) switches back.

With `--my-breaths`, every line break also counts as a breath, so you can put
each breath group on its own line instead of typing `,,,` at the end of every
one. They add up: one line break is 0.4 s, an empty line between two lines is
0.8 s, two empty lines 1.2 s, and so on. A mark at the end of a line stands in
for that line's first break (`text ,,,` then one line break is still 0.4 s).
(If a file is hard-wrapped, every wrap becomes a breath too.)

```sh
./speak --my-breaths "I built it in a weekend,,, then it broke. And I mean broke,,, the whole thing."
./speak --my-breaths --file posts/my-post.md --dry-run    # see exactly where it will pause
```

The voice also likes to take little pauses of its own mid-phrase (0.2–0.4 s,
at random, different every render). With `--my-breaths` those are cut down to
a tenth of a second, so the only real pauses are the ones you marked. Only
silence is removed; the voice itself isn't touched.

## Options reference

`./speak` / `./say` (wrappers around `scripts/index_speak.py`, the cloned voices):

```
  WORDS / --text TEXT / --file PATH
                              what to read: plain words (flags can go anywhere
                              around them), a --text string, or a file
                              (markdown auto-stripped)
  --out PATH                  output path (default: output/index_out.wav)
  --indextts / --engine NAME  breeze (Breeze TTS 2, default) or indextts (IndexTTS-2)
  --no-fast                   Breeze: skip fast mode (on by default: ~9 s
                              warm-up, then ~5x faster rendering)
  --voice NAME                reference voice (default: presenter); any name
                              also works as a bare flag: --calm, --muted, ...
  --ref PATH                  explicit reference clip path (overrides --voice)
  --ref-start / --ref-secs    which window of the reference to use (max 15s)
  --list-voices               list voices and exit
  --format {wav,ogg,both}     ogg = compressed Opus (default: wav)
  --bitrate RATE              Opus bitrate (default 48k)
  --play                      play out loud after generating
  --normalize / --no-normalize  loudness normalization (default: on)
  --lufs N                    target loudness (default -16)
  --emotion NAME              neutral (default), happy, sad, angry (IndexTTS only)
  --emo-alpha A               emotion intensity (default 0.8; IndexTTS only)
  --rate R                    speaking rate, pitch kept (0.9 = 10% slower)
  --sentence-gap / --para-gap / --breath-gap MS
                              pause after a sentence (450), paragraph (900),
                              and at each ,,, / [breath] mark (400)
  --auto-breaths / --my-breaths
                              automatic sentence/paragraph pauses plus your
                              marks (default), or pause only at your marks
  --dry-run                   print the chunks and pauses, don't render
  --fp16                      faster generation in half precision (IndexTTS only)
```

`./jarvis` (`scripts/jarvis_daemon.py`, warm Breeze server): the text as
words, `--text` or `--file`; `--voice NAME` or any voice name as a bare flag
(it sticks for later lines); `--queue` (wait for the current line instead of
interrupting it), `--my-breaths`, `--wait`, `--stop` (also clears the queue),
`--status`, `--quit`, `--list-voices`, and `--serve` (run the server in the
foreground).

`./merge` (`scripts/merge_audio.py`): `--gap-ms` sets the pause at the seam
(default 450, a sentence-to-sentence pause; ~700+ for a paragraph break).

## Setup

- NVIDIA GPU (developed on an RTX 5070 Ti, 16 GB). Model weights: ~7.7 GB
  for Breeze plus ~5.5 GB for IndexTTS-2.
- `index-tts/.venv` — PyTorch 2.8 + CUDA 12.8 venv for IndexTTS-2, and the
  Python `./speak` and `./say` start from (they hand Breeze renders over to
  Breeze's venv). Managed by `uv`; system Python 3.14 is too new for PyTorch.
- `breeze-tts/` — Breeze TTS 2, the default engine and the one behind
  `./jarvis`: its own venv (PyTorch 2.9.1 + CUDA 12.8) and 7.7 GB of weights.
  The weights and anything you generate with them are licensed for
  non-commercial use only.

  ```sh
  git clone https://github.com/breezeblue-ai/breeze-tts
  uv venv --python 3.12 breeze-tts/.venv
  uv pip install --python breeze-tts/.venv/bin/python torch==2.9.1 torchaudio==2.9.1 \
      --index-url https://download.pytorch.org/whl/cu128
  uv pip install --python breeze-tts/.venv/bin/python -r breeze-tts/requirements.txt
  breeze-tts/.venv/bin/hf download BreezeBlue/Breeze-TTS-2 --local-dir breeze-tts/breeze-tts-2
  ```
- `ffmpeg` on PATH for playback, normalization, and merging.

## Layout

```
speak, say, jarvis, jarvis-ui, merge    bash wrappers (see above)
scripts/index_speak.py    cloned-voice narration (Breeze TTS 2, or IndexTTS-2 with --indextts)
scripts/jarvis_daemon.py  warm Breeze server behind jarvis
scripts/jarvis_ui.py      the local web server behind jarvis-ui
ui/jarvis.html            the Jarvis page itself
conversations/            conversations saved from the Jarvis page (JSON)
articles/                 articles open in the Jarvis page (JSON, saved as you type)
scripts/merge_audio.py    join two clips with a natural pause
scripts/prep_ref.sh       clean a reference clip out of any audio/video
scripts/audio_common.py   shared helpers (markdown stripping, normalization, pacing marks)
voice_samples/            raw voice recordings (+ processed/ cleaned clips)
posts/                    blog posts to read (.md or .txt)
output/                   generated audio
.claude/skills/           the slash commands (this project only)
index-tts/                IndexTTS-2 repo, its .venv, checkpoints/ (5.5 GB)
breeze-tts/               Breeze TTS 2 repo, its .venv, breeze-tts-2/ weights (7.7 GB)
```

## Acknowledgements

The cloning models are [IndexTTS-2](https://github.com/index-tts/index-tts) by
the Index team at Bilibili and [Breeze TTS 2](https://github.com/breezeblue-ai/breeze-tts)
by BreezeBlue. This repo is the plumbing around them. (F5-TTS and Zonos were
evaluated and removed: F5 mispronounced words with no way to fix it, Zonos
didn't sound like me. CosyVoice3 and IndexTTS-2.5 lost a side-by-side
listening test. [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), a
fast canned voice, was dropped once Jarvis made the cloned voice fast enough.)
