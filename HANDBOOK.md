# consumer HANDBOOK — MediaPlural adapter recipes

> Core repo is dependency-free by design. This file is where OUR wiring lives:
> how the distilled corpus plugs into gbrain, the keyword lanes, and rendermill.
> External adopters ignore this file entirely.

## 1. Brain page (gbrain assimilation)

After `distill.py` produces a corpus, file one brain page per course under
`sources/` (primary subject = the course), plus per-lesson pages under
`media/courses/<course-slug>/`:

```markdown
# {Course Title} — Course Page

**Source:** acquired via consumer/scrape.py — see acquisition.json in the media dir
**Format:** course (N lessons, M minutes audio)
**Distilled:** YYYY-MM-DD, consumer v0.1

## Summary

{2–4 sentences: what the course teaches, who it's for}

## Keywords (from distill keywords.json)

{top 20 terms with tf/documents — these feed the keyword lanes}

## Concepts

{top concepts from concepts.json}

## Next-best-sentence seeds

{top seeds — candidate openers for marketing surfaces, per the
SELF-IDENTIFICATION-LOOP-SPEC and RESEARCH-TO-CREATIVE-LOOP-SPEC}

## Lesson index

- [Lesson 1 — title](lesson-01) (4.2 min) — transcript: media/courses/{slug}/lesson-01.txt
  ...
```

Filing rule: follow `skills/_brain-filing-rules.md` — file by primary subject (the course), not by format; entity extraction + back-links per media-ingest phases.

## 2. Keyword lanes (research components)

The `keywords.json` output is direct food for the per-platform keyword lanes
(RESEARCH-TO-CREATIVE-LOOP-SPEC Stage 1):

- Each lane (Google, YouTube, Meta, TikTok, Reddit) takes `keywords.json` as
  seed terms — run platform-specific expansion on top.
- The `next-best-seeds.json` sentences are candidate first-sentences: fuse
  with ICP language and score per Stage 4 composition.
- Convergence rule: terms appearing in ≥ half the lesson sources (the
  `documents` field) get priority — cross-source convergence is the strongest
  ranking signal, same doctrine as cross-platform convergence.

## 3. Rendermill script generation

`next-best-seeds.json` + `keywords.json` → rendermill `slides.py` config:

1. Pick top seed as the hook line (first sentence spoken in first 3s — the
   engine's hook law).
2. Build beats from concepts (one escalating beat per concept cluster).
3. Narration: STE-80 plain-language doctrine (median ~9 words/sentence,
   zero Latinate filler, one passive max).
4. Voice: Voidcaller (explainer video law, 2026-10-05); music bed from the
   Plural Sound catalog obeying the 60–90 BPM no-lyrics rule.
5. Preflight gates: hook ≤3s timing check, EXPLAINER-80 storyboard gate
   (storyboard_gate.py already in marketing/engine/).

The rendermill upgrade itself (animated backdrops via ComfyUI, clip-first
cuts, voice/music lanes) is specced in
`viiy-hq/marketing/engine/VIDEO-RENDER-BACKEND-SPEC-2026-10-02.md` §5 —
the consumer feeds it; the spec is the upgrade backlog.

## 4. Three-box deployment (fleet notes)

- **sharpe-studio** (daily driver): interactive/one-off transcription. Light use only — RSS guardian caps heavy classes at 16GB; transcription is heavy-class.
- **umbra** (M3 Ultra twin): the batch node. Course-scale runs (whole-course transcription) belong here via `ssh umbra`. Setup: `bash install.sh` there (same venv path), then run consumer.py from the repo checkout.
- **sharpepc**: Windows/Linux-class PC — use the faster-whisper backend (`--backend faster`), CPU inference.
- The venv is per-box (isolated), the repo is one clone per box (or one shared checkout via the network mount, if fleet doctrine allows).

## 5. MCP + external agents

Run `python3 mcp-server.py` and register it with any MCP client (Claude,
Cursor, our own squad's MCP config). Tools: `transcribe`, `scrape`, `distill`.
This is the "other agentic tools and mcp stuff" surface — other people's
agents drive the same pipeline ours does, with zero MediaPlural internals.
