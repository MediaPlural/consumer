# Contributing to consumer

This is a tool others help us update — by design. The core stays small,
stdlib-only, and local-first; everything else is welcome.

## The four laws (PRs are checked against these)

1. **Stdlib-only core.** No new runtime dependencies in `*.py` at the repo
   root without justification in the PR. The only sanctioned deps live in
   `install.sh` (the STT engine + yt-dlp). If a feature needs a library,
   make it an adapter (documented) or a graceful fallback.
2. **Provenance at every stage.** Any new acquisition/extraction path must
   record url/file + sha256 + tool + timestamp in its manifest
   (`acquisition.json` / `corpus.json` / `<stem>.sha256`).
3. **Never crash on weird input.** Course downloads are chaos: mislabeled
   extensions, empty zips, scanned PDFs, DRM'd ebooks. New format handlers
   degrade to flags (`needs_ocr`, `needs_transcription`, `hint`) — never
   exceptions, never silent data loss (see the unique-stem rule in
   `ingest.py`).
4. **`python3 tests/test_smoke.py` passes.** Fast, offline, no model
   download. Add a test for every new behavior. If your change touches
   `transcribe.py`, also state which box you verified a real transcription
   on.

## Where help is wanted (the good-first-issue map)

- **New format handlers** for `ingest.py` — every format is a small,
  self-contained `read_*` function (see `.odt` for the smallest example).
- **Platform recipes** for `course-dl.py` — tested notes for specific
  platforms (Kajabi/HighLevel/Gumroad/Coursera/FB): which URLs to seed,
  where media lives, cookie gotchas.
- **Insights engines** — `insights.js` / `distill.py` accept better local
  algorithms. The data contract is fixed (summary/keywords/concepts/
  next_best); the engine is swappable.
- **sitegen themes** — new brand palettes (the `--brand` flag currently
  ships dark/light).
- **Translations** of the site UI.

## Style

- Python: stdlib idioms, explicit is better, comments explain WHY (walls
  we hit are documented in code, e.g. the child-env scrub in transcribe.py).
- Commit messages: imperative subject + body that names the wall the
  change removes.
- One PR per capability. Small PRs merge fast.

## Dev loop

```bash
git clone https://github.com/MediaPlural/consumer.git
cd consumer
bash install.sh
python3 tests/test_smoke.py          # must pass before you start and before you PR
python3 transcribe.py --help         # poke at any stage CLI
```

Open an issue first for anything that adds a dependency, changes the
pipeline's file contracts (manifests, transcript JSON shape), or touches
the MCP tool schemas — those are the compat surfaces.