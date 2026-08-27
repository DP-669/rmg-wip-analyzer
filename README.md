# rMG WIP Analyzer

Analysis of work-in-progress composer tracks, with a verification gate so the
model cannot invent an analysis of audio it never received.

Separate from the Publisher Final Delivery app. Nothing here touches it.

---

## Why the gate exists

Gemini will produce a confident, well-structured, entirely fabricated analysis
if handed audio it cannot actually hear — complete with timestamps and section
breakdowns. There is no way to tell that output apart from a real one by
reading it.

So every track goes through this sequence:

1. The file is fetched to local disk.
2. Its true duration is measured locally with `ffprobe`.
3. The raw bytes are uploaded to the Gemini Files API — not a link.
4. Gemini is asked what it hears: duration, first audible event, three events
   in the first fifteen seconds.
5. Its reported duration is compared against the measured one. More than five
   seconds or five percent of drift and the track is **flagged and skipped**.
6. Only past that gate does the real analysis run.

A flagged track produces no analysis. That is the intended behaviour.

---

## What it assesses

Composition, function and form. Specifically: which form the cue is in
(three-act, slow burn, other), the structure map, whether material develops or
merely repeats, whether the back end genuinely culminates, sonic hooks and how
they evolve, dialogue space, edit points, and length against the 2:30–3:30
window.

**It does not assess mix.** No EQ, masking, stereo imaging, phase, loudness or
frequency claims. Gemini receives audio downsampled and summed to mono, so any
such claim would be invented. The prompt forbids them.

The standards come from Sonic Maps, distilled into `core/prompts.py`. Composers
never see the book — they see the principles applied to their track.

---

## Getting tracks in

Four routes, all ending in the same queue:

| Route | Use when |
|---|---|
| Pick files | iPad — the Files app reaches Dropbox. Also drag-and-drop on desktop. |
| Paste links | Fastest. One Dropbox file link per line. |
| Dropbox folder | Lists every audio file at any depth. Needs a Dropbox token. |

Folder position is never trusted to mean anything. Tracks are chosen by name,
not by which folder they happen to sit in.

MP3, WAV, AIFF, FLAC, M4A all process. Anything off the WIP spec (MP3 / 48 kHz
/ 320 kbps) is flagged in the results but still analyzed.

---

## Processing

One track at a time, sequentially, each in its own Gemini session with no
context carried between them. Results appear as each finishes. A failure flags
that track and the run continues. At the end, every failure is listed with what
happened and what to do about it.

---

## Setup

**Secrets** — in Streamlit Cloud, under Settings → Secrets:

```toml
GEMINI_API_KEY = "..."
DROPBOX_ACCESS_TOKEN = "..."   # optional; folder listing only
```

Without the Gemini key the app runs but cannot analyze. Without the Dropbox
token everything works except folder listing.

**Local run:**

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="..."
streamlit run app.py
```

`ffmpeg` must be present. `packages.txt` installs it on Streamlit Cloud. If it
is missing, the app falls back to `mutagen` for duration, which is enough for
the gate but reports less about the file.

---

## Files

```
app.py              Streamlit interface
core/prompts.py     Sonic Maps distilled — the analysis standards
core/audio.py       Local duration and format inspection
core/sources.py     Dropbox links, folder listing, uploads
core/gemini.py      Upload, gate, analysis
core/render.py      Results and failure reports
```

---

## Verified and not verified

Tested and working: all modules import and compile; the app boots and serves;
duration and format detection against real MP3, WAV and off-spec files; the
HTML-instead-of-audio trap; Dropbox link rewriting including `scl/fo` folder
detection; gate tolerance maths across durations; prompt assembly for all three
catalogs; result and failure rendering.

**Not yet verified: the live Gemini calls.** No API key was available at build
time, so upload, gate and analysis have never run against the real service. The
model string `gemini-3.1-pro-preview` is carried over from the existing PFD
engine and has not been re-confirmed against current Google documentation. First
run is the real test — expect to adjust.
