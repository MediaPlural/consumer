# consumer

**A big concept from a course — configured to work for our systems.** The course consumer / assimilator: point it at any course (video lessons, webinar recordings, web pages, PDFs), and it acquires, transcribes, and distills the material into a structured, keyword-annotated corpus that our agents, our brain, and our renderers consume directly.

> This repo is the packaging of MediaPlural's internal course-ingest pipeline. It is designed for others to adopt and help extend — see [CONTRIBUTING.md](CONTRIBUTING.md). Internal wiring (gbrain, rendermill, keyword lanes) is documented in [HANDBOOK.md](HANDBOOK.md) as thin adapters, not baked in.

## Why this shape

Every real-world course-consumption pipeline hits the same walls:

1. **Acquisition** — course media lives behind platforms (YouTube, Vimeo, course platforms), web pages, and PDFs. Tools: `yt-dlp` + stdlib fetch.
2. **Transcription** — video/audio → word-timestamped text. Tool: local Whisper-class STT (MLX Whisper on Apple Silicon; faster-whisper elsewhere). **Local-first: no per-minute API tax, no content leaving the machine.**
3. **Distillation** — transcripts → keywords, concepts, next-best-sentence seeds, course map. Tool: local scoring pass (stdlib only, no API key).
4. **Assimilation** — the distilled corpus becomes usable knowledge: brain pages, research components, rendermill scripts. These are adapters (see HANDBOOK.md), not core.

The core (this repo) is deliberately **stdlib-only + one STT dependency**. Everything else plugs in.

## The pipeline

```
acquire (scrape.py)      → media + acquisition.json (url, sha256, tool, timestamp)
transcribe (transcribe.py) → <stem>.transcript.json + .txt + .srt + .sha256
distill (distill.py)     → keywords.json + concepts.json + next-best-seeds.json + course-map.md
assimilate (adapters)    → brain page / keyword lanes / rendermill script  [HANDBOOK.md]
```

Every stage is idempotent and provenance-anchored: the sha256 of the source media anchors the manifest, and the transcript fingerprints its source file. Re-runs are cheap; nothing silently loses its origin.

## Install

```bash
bash install.sh            # creates ~/.hermes/venvs/consumer (mlx-whisper on Apple Silicon, faster-whisper elsewhere)
export CONSUMER_VENV_PYTHON=~/.hermes/venvs/consumer/bin/python
```

Alternative venv dirs are fine: `bash install.sh ~/my-venv` then pass `--venv-python`.

## Usage

```bash
# 1. Acquire a lesson (video platform link or web page)
python3 scrape.py "https://www.youtube.com/watch?v=XXXX" --out-dir ./course/media --audio-only
python3 scrape.py "https://some-course-platform.com/lesson-page" --out-dir ./course/pages

# 2. Transcribe everything in a directory
python3 transcribe.py ./course/media/lesson-01.m4a --out-dir ./course/transcripts

# 3. Distill the corpus
python3 distill.py ./course/transcripts --out-dir ./course/distilled

# 4. Assimilate: feed the distilled corpus to your agent / brain / renderer.
#    (MediaPlural adapters in HANDBOOK.md.)
```

There is also a single-command wrapper for the whole pipeline:

```bash
python3 consumer.py "URL-or-directory" --tag my-course     # acquire → transcribe → distill
```

## Provenance & pins

| Component           | Pin                                                                                                                      | Why                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| STT (Apple Silicon) | `mlx-whisper==0.4.3`, model `mlx-community/whisper-large-v3-turbo` @ revision `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb` | exact model+revision provenance, verified live (99.7s video → 46 segments in 4.5s) |
| STT (Linux/other)   | `faster-whisper` (latest)                                                                                                | CTranslate2 CPU inference; same output shape                                       |
| Acquisition         | `yt-dlp` (latest)                                                                                                        | moving target by design; acquisition manifest records what ran                     |
| Everything else     | Python stdlib                                                                                                            | adopt-don't-rebuild law: zero API keys, zero cloud calls in core                   |

## Directory layout

```
consumer/
├── README.md            # this file
├── CONTRIBUTING.md      # how others help extend (the "tool others help us update" contract)
�        └── INGEST.md    # machine-readable load order for agents
├── install.sh           # isolated venv setup
├── transcribe.py        # video/audio → word-timestamped transcript (+txt/srt/sha256)
├── scrape.py            # URL → media/page (yt-dlp / stdlib fetch) + acquisition manifest
�        ├── distill.py   # corpus → keywords/concepts/seeds/course-map
├── consumer.py          # one-command wrapper: acquire → transcribe → distill
├── HANDBOOK.md          # adapter docs for MediaPlural systems (gbrain, rendermill, keyword lanes)
├── mcp-server.py        # MCP server: tools = transcribe/scrape/distill/status (agents drive it)
�        └── tests/      # smoke tests (no model download needed)
├── tests/
│   └── test_smoke.py    # CLI-shape + manifest + distiller unit tests (fast, offline)
```

## Design law (why others adopt rather than rebuild)

- **Local-first.** Transcription never leaves the machine. The model weight is a pinned asset; the venv is isolated; the child env is scrubbed (host PYTHONPATH leaks are a real failure mode — see transcribe.py header).
- **Provenance-anchored.** sha256 of source media in the acquisition manifest; transcript fingerprints its source. Any output can be traced back to exact input bytes.
- **Stdlib-only core.** The only dependencies are the STT engine and yt-dp. Everything else is stdlib — so adoption is a git clone plus one venv.
- **Adapters over integrations.** No gbrain/rendermill imports in core. Adapters live in HANDBOOK.md as copy-paste recipes, so external users get a clean core and internal wiring stays ours.
- **Agent-first.** INGEST.md + MCP server mean both our squad and other people's agents can drive the pipeline mechanically.

## License

MIT. Fork it, extend it, PR it back — that's the point.

## Paste-ready: run it anywhere

One package, four paste surfaces — terminal, any AI, any coding agent, any browser. All equivalent.

**Terminal (macOS / Linux):**

```bash
git clone https://github.com/MediaPlural/consumer ~/consumer && \
  bash ~/consumer/install.sh && \
  python3 ~/consumer/source.py https://example.com --full
```

**Any AI agent (Claude, ChatGPT, Viiy, any MCP client):**

```
Read https://ingest.fm/consumer/INGEST.md and execute its load order; it routes everything else.
```

**Claude Code / Cursor / OpenClaw / VS Code / Hermes — one script detects and installs for every runtime present:**

```bash
git clone https://github.com/MediaPlural/consumer ~/consumer && bash ~/consumer/install-everywhere.sh
```

**Any browser:** open https://ingest.fm/consumer (public; ingest.my aliases it, viiy.to is the personal host) — the post page carries the same blocks, clickable and copyable.

The INGEST.md manifest at the package root routes everything: load order, file map, sha256 fingerprint.

## The integration bank

`bank.py` — our answer to IFTTT/Zapier/Composio, with the custody law intact:
local-first auth (ortie/keychain), optional self-hosted Nango for the long
tail, community-extendable via declarative manifests
(`bank/connectors/*.json` — `bank.py add-manifest` validates and installs).
Consume lanes pull archives into the graph; act lanes run declared actions
through a shell-injection-proof runner (shlex-quoted args, no shell=True).
See [INTEGRATIONS.md](INTEGRATIONS.md) for the landscape and our position.
