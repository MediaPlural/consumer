---
name: consumer
version: 0.3.0
description: |
  Use when consuming ANY knowledge material into a structured, attributed,
  queryable knowledge graph — courses, videos, audio, books, PDFs, spreadsheets,
  slide decks, web pages, platform courses (skool/Kajabi/HighLevel/Gumroad/
  Coursera), email archives, the screen — or creating courses/training sites
  FROM consumed knowledge. The knowledge consumer: acquire, transcribe (local
  STT), ingest any format, distill, graph, query (search/semantic/hybrid/
  filter/insight/maths), author, explain, learn. Local-first, stdlib-only,
  provenance-anchored, deterministic embeddings.
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

# Consumer — the knowledge consumer / engine of enlightenment

One engine, every runtime. This SKILL.md speaks the AgentSkills dialect
(Hermes, Claude Code, OpenClaw, Cursor) and is carried by runtime adapters
below for non-AgentSkills runtimes (VS Code/Copilot via MCP, any MCP client).

Repo: `https://github.com/MediaPlural/consumer` (MIT). Local checkout:
run `CONSUMER_HOME` discovery below; default `/Users/sharpe/consumer`
(studio), `~/consumer` (umbra), `tools/consumer` in the refurbapp worktree.

## Universal invocation law

**All commands are plain shell commands.** The engine is CLI-first: every
runtime invokes it the same way regardless of who is driving. Runtime
differences are only HOW tools are called:

- **Hermes**: terminal / execute_code tools
- **Claude Code**: Bash tool (or slash command `/consumer` if installed)
- **OpenClaw**: shell tool (or slash command via user-invocable skill)
- **Cursor**: terminal tool (or the .cursor rule)
- **VS Code/Copilot**: the MCP server (graph_query etc.) or integrated terminal
- **Any MCP client**: `consumer-mcp` stdio server (5 tools)

## Locate the engine

The engine is a directory with bank.py/graph.py/ingest.py. Find it:

```
[ -d /Users/sharpe/consumer ] && CONSUMER_HOME=/Users/sharpe/consumer
[ -d "$HOME/consumer" ] && CONSUMER_HOME="$HOME/consumer"
[ -d "tools/consumer" ] && CONSUMER_HOME="tools/consumer"
[ -z "$CONSUMER_HOME" ] && CONSUMER_HOME=$(find ~ -maxdepth 3 -name bank.py \
    -path "*/consumer/bank.py" 2>/dev/null | head -1 | xargs dirname)
```

The installer pins the resolved path at install time. The skill dir may be
carried by a package/zip moved between machines — resolve first, always.

## The three-layer loop

### LAYER 1 — CONSUME
Point at ANYTHING. `source.py` is the universal front door:
```
python3 source.py <url-or-path> --full          # chains ingest+graph
python3 source.py course:<course-url>           # platform course crawls
python3 source.py website:<url>                 # whole-site crawl
python3 source.py dir:<path> | zip:<file> | gdrive:<id-or-link> | file:<path>
python3 source.py screen                        # zero-in screen lane
python3 source.py screen --live --interval 5   # live screen watch
```
Local STT: `transcribe.py` (MLX Whisper large-v3-turbo pinned rev, isolated
venv at ~/.hermes/venvs/consumer; scrub PYTHONPATH/VIRTUAL_ENV/CONDA in child
envs; ffmpeg on PATH). OCR lane: `ocr.py` for image-born content. Bank
connectors: `bank.py list/status/consume/act` (gmail/imap/drive/skool/http/
zero-in; community manifests bank/connectors/*.json; SAFE runner: shlex-quoted,
no shell=True).

### LAYER 2 — ASSIMILATE
ingest.py (10+ formats, magic-sniffed, idempotent) -> distill.py (concepts,
links, convergence-boosted scoring) -> refine.py (near-dup chunk dedup
cosine>0.97, morphological concept merge) -> graph.py (vectorized graph:
sqlite+FTS5+deterministic blake2b 512-dim embeddings; query modes: search/
semantic/hybrid/filter/insight/maths; bridges = concepts spanning >=2 sources).

### LAYER 3 — CREATE + INTEGRATE
author.py (clusters corpus into course shape), explain.py (step-by-step
explainers), sitegen.py (responsive site w/ floating ToC, AI summaries,
game-engine XP hook), insights.js (the {AgentName} Insights widget law),
export.py (json/jsonl/csv/md/sqlite/package), sync.py (import/merge, dedup),
api.py (HTTP API, 8 routes, localhost:8765), connectors.py (gmail/imap/drive),
bank.py (integration bank, consume+act lanes).

## Runtime adapters

- **Hermes** (installed): `~/.hermes/skills/consumer`. Install/refresh:
  `bash install-skill.sh`; every runtime: `bash install-everywhere.sh`.
  Install-skill.sh also refreshes the Claude Code install when present.
  Claude Code: `~/.claude/skills/consumer`. OpenClaw: `~/.openclaw/skills/
  consumer` (created by install-everywhere.sh; OpenClaw not yet installed on
  studio, see SKILL.md "OpenClaw" section). Cursor: `.cursor/skills/consumer`
  (project) or user Agent Store — the .mdc rule (install-everywhere.sh
  writes `.cursor/rules/consumer.mdc`) fires on intelligent matching.
  VS Code/Copilot: the MCP server registered in `.vscode/mcp.json` +
  `settings.json` (user profile) by install-everywhere.sh.
  See `docs/RUNTIMES.md` for full layout.
- **Any MCP client** (incl. remote agents): `consumer-mcp` stdio server,
  `python3 mcp-server.py`, 5 tools (source, transcribe, scrape, distill,
  graph_query). Graph db: `$CONSUMER_GRAPH_DB` (default `consumer.graph.db`).

## Laws

- Local-first, custody law: credentials via segmented store
  `~/.consumer/creds/<platform>/` (Muse pattern, Broker-only) or keychain;
  never in code, logs, or argv.
- Attribution is inbuilt, end-to-end: url + credential-identity + timestamp
  flow from acquisition -> corpus -> graph -> query results.
- Deterministic embeddings: same text = same vector forever; cross-graph
  cosine without shipping models.
- No DRM/paywall breaking, no trial farming, owned material only.
- The SAFE runner: shlex-quote every substituted value, argv execution,
  no shell=True. Bank manifests declare capabilities; add-manifest validates.

## Verifications (all live-tested)

- 57/57 tests (studio + Brandon worktree), 55/55 umbra
- STT: 99.7s video -> 46 segments in 4.5s
- gmail consume: 15 real messages -> 861 chunks
- OCR: rendered PNG -> 100% correct text
- Injection resistance: `; touch /tmp/pwned.txt` stayed literal
- watch-mode: mid-watch drop detected in 2s
- Attribution end-to-end: scrape -> search result carries URL + tool
- Round-trip: build -> export package -> import fresh db -> merge dedup holds
