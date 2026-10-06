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
  - "run a connector"
  - "bank status"
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
https://github.com/MediaPlural/consumer (MIT). **The engine of
enlightenment**: consume, assimilate, integrate everything — then discover
new insights and synthesis. Courses are ONE input shape; point it at
websites, zips, gdrive, folders, any knowledge material.

## The loop (three layers)

1. **CONSUME**: source.py (point at ANYTHING) → ingest.py (any format) →
   transcribe.py (local STT) — the acquisition layer
2. **ASSIMILATE**: distill.py (keywords/concepts/seeds) → graph.py (the
   vectorized graph: sqlite + FTS5 + deterministic hashed embeddings,
   concept co-occurrence links, cross-source bridges)
3. **DISCOVER**: graph.py queries — search / semantic / hybrid / filter /
   insight / maths — plus create facet (author.py, explain.py, sitegen.py)
   turning what's assimilated into new works

## The tools

| Stage | Tool | Job |
|---|---|---|
| point | `source.py` | ANY source (website/zip/gdrive/dir/course URL) → workspace + auto ingest + auto graph (`--full`) |
| acquire | `course-dl.py` | whole-course crawl (skool/Kajabi/HighLevel/Gumroad/Coursera/any) |
| fetch one | `scrape.py` | single URL → media/page + manifest |
| ingest | `ingest.py` | any-format extraction: csv/xlsx/docx/pptx/epub/pdf/svg/md/srt/vtt + magic-byte sniffing |
| transcribe | `transcribe.py` | LOCAL STT (MLX Whisper / faster-whisper), word timestamps |
| distill | `distill.py` | keywords, concepts, next-best-seeds, course map |
| **graph** | `graph.py` | **the assimilated knowledge graph** — query 5 ways (below) |
| author | `author.py` | draft courses from corpora (`new`/`from-corpus`/`edit`) |
| explain | `explain.py` | corpus → rendermill-compatible explainer + storyboard |
| learn | `sitegen.py` | course site: ToC/Insights/XP/editions/training |
| insights | `insights.js` | "{Agent} Insights" one-tap panel |
| trial | `trial.py` | honest trial lifecycle |
| creds | `creds.py` | segmented credential store (Muse pattern) |
| refine | `refine.py` | clean/organize/match: dedup chunks + morphological concept merge |
| **zero-in** | `zero.py` | consume EXACTLY what's on screen: region/window/fullscreen/clipboard -> OCR -> graph |
| connectors | `connectors.py` | app archives via real auth: gmail (ortie OAuth), imap (app password), drive |
| **bank** | `bank.py` | the integration bank: connector registry (community manifests), consume + act lanes, auth health |
| export | `export.py` | ALWAYS-LEAVE law: json/jsonl/csv/md/sqlite/package (INGEST.md convention) |
| api | `api.py` | graph over HTTP: /search /semantic /hybrid /filter /insight /maths /export |
| sync | `sync.py` | merge/import-jsonl/import-package — syncable anywhere |

## The graph (graph.py) — the discovery engine

```bash
python3 graph.py ingest CORPUS_DIR --db graph.db           # build from corpus.json+extracted/
python3 graph.py search "affiliate*" --db graph.db         # FTS (prefix queries need *)
python3 graph.py semantic "payout structures" --db graph.db  # cosine, no model needed
python3 graph.py hybrid "recurring commission" --db graph.db # FTS+semantic fused
python3 graph.py filter --kind text --source csv --db graph.db
python3 graph.py insight --bridges 15 --orphans --db graph.db # cross-source bridges = discovery
python3 graph.py maths --db graph.db                       # corpus statistics
```

Deterministic hashed embeddings (blake2b token-ngrams → 512-dim, L2-normalized):
same text = same vector forever, no model download, no API. Concept
co-occurrence links + **bridges** (concepts spanning ≥2 sources) are where
new synthesis lives — integration makes visible what no single source says.

## Point-at-anything (source.py)

```bash
python3 source.py https://site.com/docs --workspace ./ws --full --db g.db
python3 source.py ~/Downloads/course-export.zip --workspace ./ws --full --db g.db
python3 source.py "https://drive.google.com/file/d/ID/view" --workspace ./ws --full --db g.db
python3 source.py ~/my-course --workspace ./ws --full --db g.db
```
`--full` chains ingest + graph automatically. GDrive: public files work;
private folders → use Drive's "Download as ZIP".



## Zero-in + app connectors (agent-native triggers)

```bash
# zero-in — the Foxy-select/Omnisight trigger: consume exactly what's visible
python3 zero.py --region   --db g.db          # drag a box
python3 zero.py --window   --db g.db          # click a window
python3 zero.py --fullscreen --db g.db         # everything
python3 zero.py --clip      --db g.db --label "note"   # clipboard

# app connectors — "consume my email archive" with real auth
python3 connectors.py list
python3 connectors.py auth gmail                        # one-time OAuth (ortie)
python3 connectors.py export gmail --since 2026-01-01 --limit 500 --db g.db
python3 connectors.py export imap --host imap.gmail.com --user you@gmail.com --db g.db
#   IMAP password: env CONSUMER_IMAP_PASS or keychain (security add-generic-password -s consumer-imap)
```

Credential law unchanged: tokens live in ortie (never in commands/logs);
IMAP passwords in env/keychain, never argv.

## Interop — always able to leave (the always-leave law)

The user is never locked in. Everything assimilated exports and syncs freely:

```bash
python3 export.py g.db --format package --outdir share/ --title "T"  # INGEST.md manifest + fingerprint
python3 export.py g.db --format jsonl --out chunks.jsonl            # RAG/vector-db feed
python3 export.py g.db --format csv --outdir csv/                    # spreadsheets/SQL/BI
python3 export.py g.db --format sqlite --out copy.db                # standalone db copy
python3 api.py --db g.db --port 8765                                # HTTP: any tool, any language
python3 refine.py g.db [--apply]                                    # clean/organize/match
python3 sync.py import-package share/ --db other.db                 # bring a package in
python3 sync.py merge left.db right.db --out merged.db              # union with dedup
```

Box-to-box: export package on A → move the dir (scp/gdrive/usb) →
import-package on B. Live: api.py on A, any HTTP client on B. Cross-graph
cosine works without shipping models (deterministic hashed vectors).

## Setup

```bash
bash install.sh && export CONSUMER_VENV_PYTHON=~/.hermes/venvs/consumer/bin/python
python3 tests/test_smoke.py            # green before anything
bash install-skill.sh                  # load as a Hermes skill
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