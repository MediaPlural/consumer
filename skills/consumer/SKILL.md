---
name: consumer
version: 0.2.0
description: |
  Use when consuming ANY knowledge material into structured corpus — courses,
  videos, books, PDFs, spreadsheets, slide decks, web pages, platform courses
  (skool/Kajabi/HighLevel/Gumroad/Coursera) — or creating courses, training
  sites, and explainer videos FROM consumed knowledge. The knowledge consumer:
  acquire, transcribe (local STT), ingest any format, distill, author, explain,
  learn. Local-first, stdlib-only, provenance-anchored.
triggers:
  - "consume this course"
  - "download all module content"
  - "get the whole course"
  - "skool course"
  - "transcribe these videos"
  - "ingest these files"
  - "distill this corpus"
  - "author a course"
  - "make an explainer from this"
  - "start a trial"
  - "knowledge consumer"
tools:
  - terminal
  - execute_code
  - browser_exec
  - web_extract
mutating: true
writes_to:
  - consumer-out/
  - acquired/
  - course-dl/
  - transcripts/
  - distilled/
  - site/
upstream: MediaPlural/consumer
---

# Consumer — the knowledge consumer/assimilator

Repo: `/Users/sharpe/consumer` (umbra: `~/consumer`). Public:
https://github.com/MediaPlural/consumer (MIT). Courses are ONE FACET —
the same pipeline consumes any knowledge material and produces structured
corpus + new authored artifacts.

## The tools (stage → tool → job)

| Stage | Tool | Job |
|---|---|---|
| acquire | `course-dl.py` | whole-course crawl (skool/Kajabi/HighLevel/Gumroad/Coursera/any): pages, files, videos → `acquisition.json` |
| fetch one | `scrape.py` | single URL → media/page + manifest |
| ingest | `ingest.py` | any-format text extraction: csv/xlsx/docx/pptx/epub/pdf/svg/md/srt/vtt + magic-byte sniffing → `corpus.json` |
| transcribe | `transcribe.py` | LOCAL STT (MLX Whisper Apple Silicon / faster-whisper elsewhere), word timestamps → transcript JSON/TXT/SRT/sha256 |
| distill | `distill.py` | corpus → keywords/concepts/next-best-seeds/course-map |
| author | `author.py` | draft new courses from corpora (`new`, `from-corpus`, `edit`) |
| explain | `explain.py` | corpus → rendermill-compatible explainer project + zero-dep storyboard |
| learn | `sitegen.py` | course site: floating ToC, per-lesson Insights, XP, edition export, training packages |
| insights | `insights.js` | "{Agent} Insights" one-tap panel for any DOM surface |
| trial | `trial.py` | honest trial lifecycle (one per platform, cancel on time) |
| creds | `creds.py` | segmented credential store — broker-only, identity-only provenance |
| wrapper | `consumer.py` | URL/dir → acquire+transcribe+distill in one command |
| agents | `mcp-server.py` | MCP tools: transcribe/scrape/distill |

## Decision table (user says → run)

```bash
# setup once per box (isolated venv; NEVER pip-install into a shared env)
bash install.sh && export CONSUMER_VENV_PYTHON=~/.hermes/venvs/consumer/bin/python
python3 tests/test_smoke.py            # 22/22 green before anything

# "consume this course" (platform course, member access)
python3 creds.py import skool cookies.txt          # once; jar MOVES into the store
python3 course-dl.py "https://www.skool.com/X/classroom" --platform skool --out-dir ./course

# "transcribe these videos"           # "ingest these files" (any format)
python3 transcribe.py FILE --out-dir ./transcripts
python3 ingest.py DIR --recursive

# "distill this corpus"
python3 distill.py ./transcripts --out-dir ./distilled

# one command for URL or media dir:
python3 consumer.py URL-OR-DIR --tag my-course

# "author a course from this" / "make an explainer"
python3 author.py from-corpus ./distilled --title "T" --out ./edition
python3 explain.py ./distilled --title "T" --out ./explainer
# rendermill installed: cd explainer && rendermill render

# "course site" (ToC/Insights/XP/training)
python3 sitegen.py ./distilled --lessons ./transcripts --title "T" --out ./site/index.html
```

## The earned traps (do not re-learn these)

1. **STT child env**: the bridge interpreter runs with PYTHONPATH/VIRTUAL_ENV/
   CONDA* scrubbed — host kernels leak site-packages into subprocesses and
   break the venv (verified failure). ffmpeg's dir MUST be on the child PATH.
2. **Heavy STT runs on umbra, not the daily driver** — the RSS guardian caps
   heavy classes; batch transcription is heavy-class (fleet doctrine).
3. **PDF extractor**: linear str.find + single-char-class regex ONLY. The
   lazy-quantifier version hit catastrophic backtracking (300s+ hang on
   multi-MB binaries).
4. **Never trust extensions**: magic-byte sniff first — real course downloads
   contain a ".pptx" that is really a PDF, a ".docx" that is really UTF-8 text.
5. **Unique output stems**: flat stems let six formats overwrite each other
   (silent data loss). Full rel-path stem + collision suffix.
6. **skool**: lesson URLs are `?md={32-hex}` harvested from classroom page
   source (no JS); Cloudflare Stream needs `--referer https://www.skool.com`;
   lesson interiors need member cookies. Public crawl captures course cards.
7. **Credentials (Muse pattern)**: cookies/tokens live ONLY in
   `~/.consumer/creds/<platform>/` (0700/0600). creds.Broker is the only
   reader; manifests record `platform:skool` identity, never values; error
   text redacted. Never paste cookies into a command line.
8. **stdlib MozillaCookieJar breaks on real exports** (domain-dot assertion)
   — the broker's tolerant parse is load-bearing; don't "simplify" it back.
9. **Trials**: one active per platform (enforced). Consume honestly, cancel
   on time — trial.py is a lifecycle manager, not a farming tool.
10. **DOM selectors**: scope to the component (`.lesson[data-lesson=…]`) —
    global attribute selectors get shadowed by nav/ToC elements (the live
    browser test caught XP showing 0 with the lesson visibly complete).
11. **XML from untrusted files**: entity/DOCTYPE guard before parsing
    (billion-laughs); OOXML never carries DTDs so legit files pass.
12. **DRM is a hard line**: ingest DRM-free exports (EPUB) fine; DRM'd
    Kindle formats get byte-registered with conversion hints, never stripped.

## Provenance law

Every stage anchors its outputs: scrape/course-dl → `acquisition.json`
(url, sha256, tool, timestamp, credential identity); transcribe →
`<stem>.sha256` + pinned model/revision in the JSON; ingest → `corpus.json`;
distill reads, never mutates. Any output traces to exact input bytes.

## Agent surfaces

- **MCP**: run `python3 mcp-server.py` — tools `transcribe`, `scrape`,
  `distill` (initialize/tools/list/tools/call JSON-RPC over stdio).
- **INGEST.md** in the repo root: machine-readable pipeline map for agents.
- **Insights widget**: `insights.js` + `Insights.mountAll({agentName})` on any
  page; data contract: summary/keywords/concepts/next_best (INSIGHTS.md).

## Anti-patterns

- Piping a cookie value into a shell command instead of `creds.py import`
- Running whole-course transcription on the daily driver when umbra is idle
- Skipping the smoke suite after touching any tool
- Vendoring piecemeal (cherry-picks drift the shared schema — re-vendor whole)
- Presenting author.py drafts as finished writing — they are scaffolds