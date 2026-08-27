# COWORK TASK — rmg-wip-analyzer repo + deploy prep

Priority: MEDIUM | Owner: Cowork | Added: 2026-08-26

Source files: attached to this task / in Damir's Downloads as `rmg-wip-analyzer/`.
New standalone app. Does NOT touch the PFD app or rMG-Hub.

## STEP 1 — Create the repo
Create a new PRIVATE GitHub repo under DP-669 named `rmg-wip-analyzer`.
Push the folder contents as the initial commit.
Commit message: "rMG WIP Analyzer — verified Gemini audio analysis, initial commit"

Do NOT commit any secrets. `.gitignore` already excludes
`.streamlit/secrets.toml` and `.env`. Confirm neither is in the tree before push.

## STEP 2 — Confirm the model string
Read https://ai.google.dev/gemini-api/docs/models and confirm whether the
current audio-capable model identifier is `gemini-3.1-pro-preview` (what
`core/gemini.py` line ~24 uses, carried over from the PFD engine) or
`gemini-3.1-pro`.

If it differs, change MODEL_ID in `core/gemini.py` only, commit separately:
"Correct Gemini model identifier to <string>"

If you cannot reach the docs, report UNVERIFIED. Do not guess.

## STEP 3 — Smoke test the Gemini path locally
This is the part that has never run. Using Damir's Gemini API key from Keychain:

    cd rmg-wip-analyzer
    pip install -r requirements.txt --break-system-packages
    export GEMINI_API_KEY="$(security find-generic-password -s <keychain-entry> -w)"
    python3 -c "
    from core import audio, gemini
    c = gemini.make_client(__import__('os').environ['GEMINI_API_KEY'])
    p = '<path to any real MP3 on disk>'
    info = audio.inspect(p)
    print('local duration:', info['duration_display'])
    r = gemini.analyze_track(c, p, info, 'SSC', '')
    print('gate drift:', r['gate']['_drift_seconds'], 's')
    print('form:', r['analysis']['form'])
    print('notes:', len(r['analysis']['primary_notes']))
    "

Report the exact output. Three outcomes:
- Gate passes, analysis returns → WORKING, proceed to step 4
- Gate fails on a file you know is fine → report the drift numbers, do not
  loosen the tolerance without Damir's approval
- SDK/API error → report verbatim, do not improvise fixes

## STEP 4 — Dropbox token (only if step 3 passed)
Generate a Dropbox access token scoped to the OPERATIONAL account with
`sharing.read` and `files.metadata.read`. Store in Keychain as
`rmg-dropbox-wip-token`. Report that it exists — do NOT paste the value into
ntfy, the Command Center, or any Drive document.

## VERIFY OR BLOCK
- Step 1 DONE only when the repo is visible on github.com/DP-669 and the file
  count matches (12 files).
- Step 3 DONE only when a real analysis JSON is returned. "No errors" does not
  count.
- Any step failing 4 times: stop, write a Perplexity prompt, report.

## REPORT
ntfy `Damir-rMG-2026`, title `WIP-ANALYZER-SETUP`:
repo URL, model string confirmed or corrected, step 3 result verbatim,
whether the Dropbox token was created.
