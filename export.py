#!/usr/bin/env python3
"""consumer export — everything assimilated can always leave.

The interop law: the user is never locked in. Any graph, any corpus, any
insight exports freely to other agents, tools, and databases:

  json      full graph dump (sources, chunks+vectors, concepts, links, bridges)
  jsonl     one chunk per line — the agent-feed format (RAG loaders, vector dbs)
  csv       flat tables for spreadsheets / SQL / BI (chunks.csv + concepts.csv)
  md        human/LLM-readable dossier (per-source, bridges, top concepts)
  package   a self-contained share dir with an INGEST.md manifest (the
            MediaPlural/ingest convention: BLUF + load order + file map +
            sha256 fingerprint + the recipient-agent one-liner)
  sqlite    a clean standalone copy of the graph db (other sqlite tooling)

Everything is stdlib-only. No cloud, no API, no lock-in — by construction.

Usage:
  python3 export.py GRAPH.db --format json --out dump.json
  python3 export.py GRAPH.db --format jsonl --out chunks.jsonl
  python3 export.py GRAPH.db --format csv --outdir csv-out/
  python3 export.py GRAPH.db --format md --out dossier.md
  python3 export.py GRAPH.db --format package --out share-pkg/ --title "My Corpus"
  python3 export.py GRAPH.db --format sqlite --out copy.db

Filters (apply to chunk-level formats): --source NAME, --kind KIND.
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time


def open_db(path):
    if not os.path.exists(path):
        sys.exit(f"FATAL: no graph at {path} — run: graph.py ingest <corpus_dir> --db {path}")
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def graph_data(db, source=None, kind=None):
    """Pull the whole graph as plain dicts (the universal interchange shape)."""
    where, args = [], []
    if source:
        where.append("s.name LIKE ?"); args.append(f"%{source}%")
    if kind:
        where.append("s.kind = ?"); args.append(kind)
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    sources = [dict(r) for r in db.execute(
        f"SELECT id, name, kind, path, sha256, url, credential, acquired_at, acquire_tool FROM sources s{wsql}", args)]
    sids = [s["id"] for s in sources]
    chunks = []
    if sids:
        marks = ",".join("?" * len(sids))
        for r in db.execute(
                f"SELECT id, source_id, idx, text, words, vector_json FROM chunks "
                f"WHERE source_id IN ({marks}) ORDER BY source_id, idx", sids):
            chunks.append({"id": r["id"], "source_id": r["source_id"], "idx": r["idx"],
                           "text": r["text"], "words": r["words"],
                           "vector": json.loads(r["vector_json"])})
    concepts = [dict(r) for r in db.execute("SELECT id, phrase FROM concepts")]
    chunk_concepts = [dict(r) for r in db.execute("SELECT chunk_id, concept_id, tf FROM chunk_concepts")]
    links = [dict(r) for r in db.execute("SELECT a_id, b_id, co FROM concept_links")]
    bridges = [dict(r) for r in db.execute("SELECT concept_id, source_count FROM bridges")]
    stats = {k: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
             for k, t in [("sources", "sources"), ("chunks", "chunks"),
                          ("concepts", "concepts"), ("links", "concept_links"),
                          ("bridges", "bridges")]}
    return {"exported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "stats": stats, "sources": sources, "chunks": chunks,
            "concepts": concepts, "chunk_concepts": chunk_concepts,
            "concept_links": links, "bridges": bridges}


def out_json(db, path, source, kind):
    data = graph_data(db, source, kind)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return {"format": "json", "out": os.path.abspath(path),
            "bytes": os.path.getsize(path), "stats": data["stats"]}


def out_jsonl(db, path, source, kind):
    """The agent-feed format: one chunk per line, denormalized (source name,
    concepts, vector inline) so a downstream loader needs zero joins."""
    where, args = [], []
    if source:
        where.append("s.name LIKE ?"); args.append(f"%{source}%")
    if kind:
        where.append("s.kind = ?"); args.append(kind)
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    concept_by_id = {r["id"]: r["phrase"] for r in db.execute("SELECT id, phrase FROM concepts")}
    cc_by_chunk = {}
    for r in db.execute("SELECT chunk_id, concept_id, tf FROM chunk_concepts"):
        cc_by_chunk.setdefault(r["chunk_id"], []).append((concept_by_id.get(r["concept_id"]), r["tf"]))
    n = 0
    with open(path, "w") as f:
        for r in db.execute(
                f"SELECT c.id, c.idx, c.text, c.words, c.vector_json, s.name, s.kind, s.sha256, "
                f"s.url, s.credential, s.acquired_at, s.acquire_tool "
                f"FROM chunks c JOIN sources s ON s.id = c.source_id{wsql} "
                f"ORDER BY s.id, c.idx", args):
            f.write(json.dumps({
                "chunk_id": r["id"], "idx": r["idx"], "text": r["text"],
                "words": r["words"], "source": r["name"], "kind": r["kind"],
                "source_sha256": r["sha256"],
                "url": r["url"], "credential": r["credential"],
                "acquired_at": r["acquired_at"], "acquire_tool": r["acquire_tool"],
                "vector": json.loads(r["vector_json"]),
                "concepts": [c for c, _ in cc_by_chunk.get(r["id"], [])],
            }, ensure_ascii=False) + "\n")
            n += 1
    return {"format": "jsonl", "out": os.path.abspath(path), "lines": n}


def out_csv(db, outdir, source, kind):
    os.makedirs(outdir, exist_ok=True)
    where, args = [], []
    if source:
        where.append("s.name LIKE ?"); args.append(f"%{source}%")
    if kind:
        where.append("s.kind = ?"); args.append(kind)
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    written = []
    p1 = os.path.join(outdir, "chunks.csv")
    with open(p1, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["chunk_id", "source", "kind", "idx", "words", "text"])
        for r in db.execute(f"SELECT c.id, s.name, s.kind, c.idx, c.words, c.text "
                            f"FROM chunks c JOIN sources s ON s.id=c.source_id{wsql} "
                            f"ORDER BY s.id, c.idx", args):
            w.writerow([r["id"], r["name"], r["kind"], r["idx"], r["words"], r["text"]])
    written.append(p1)
    p2 = os.path.join(outdir, "concepts.csv")
    with open(p2, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["concept_id", "phrase", "total_tf", "source_count"])
        for r in db.execute("""SELECT cp.id, cp.phrase, sum(cc.tf) tf,
                                      count(DISTINCT c.source_id) sc
                                      FROM concepts cp
                                      JOIN chunk_concepts cc ON cc.concept_id = cp.id
                                      JOIN chunks c ON c.id = cc.chunk_id
                                      GROUP BY cp.id, cp.phrase ORDER BY tf DESC"""):
            w.writerow([r["id"], r["phrase"], r["tf"], r["sc"]])
    written.append(p2)
    p3 = os.path.join(outdir, "sources.csv")
    with open(p3, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_id", "name", "kind", "sha256", "url", "credential",
                     "acquired_at", "tool", "chunks", "words"])
        for r in db.execute("""SELECT s.id, s.name, s.kind, s.sha256, s.url, s.credential,
                                      s.acquired_at, s.acquire_tool, count(c.id), sum(c.words)
                                      FROM sources s LEFT JOIN chunks c ON c.source_id = s.id
                                      GROUP BY s.id ORDER BY s.id"""):
            w.writerow(list(r))
    written.append(p3)
    return {"format": "csv", "outdir": os.path.abspath(outdir),
            "files": [os.path.basename(p) for p in written]}


def out_md(db, path):
    """Human/LLM dossier: what was consumed, what it says, what bridges it."""
    stats = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
             for t in ["sources", "chunks", "concepts", "bridges"]}
    lines = ["# Knowledge Corpus Dossier", "",
             f"Exported: {time.strftime('%Y-%m-%d %H:%M')} · "
             f"{stats['sources']} sources · {stats['chunks']} chunks · "
             f"{stats['concepts']} concepts · {stats['bridges']} bridges", ""]
    lines += ["## Sources", ""]
    for r in db.execute("""SELECT s.name, s.kind, count(c.id) n, sum(c.words) w
                            FROM sources s LEFT JOIN chunks c ON c.source_id=s.id
                            GROUP BY s.id ORDER BY s.id"""):
        lines.append(f"- **{r['name']}** ({r['kind']}) — {r['n']} chunks, {r['w'] or 0} words")
    lines += ["", "## Bridge concepts (span multiple sources — the discovery surface)", ""]
    for r in db.execute("""SELECT cp.phrase, b.source_count FROM bridges b
                            JOIN concepts cp ON cp.id = b.concept_id
                            ORDER BY b.source_count DESC, cp.phrase LIMIT 25"""):
        lines.append(f"- **{r['phrase']}** — spans {r['source_count']} sources")
    lines += ["", "## Strongest concept pairs", ""]
    cname = {r["id"]: r["phrase"] for r in db.execute("SELECT id, phrase FROM concepts")}
    for r in db.execute("SELECT a_id, b_id, co FROM concept_links ORDER BY co DESC LIMIT 15"):
        lines.append(f"- {cname.get(r['a_id'])} + {cname.get(r['b_id'])} (co-occur {r['co']}x)")
    lines += ["", "## Per-source concept richness", ""]
    for r in db.execute("""SELECT s.name, count(DISTINCT cc.concept_id) n
                            FROM sources s JOIN chunks c ON c.source_id=s.id
                            JOIN chunk_concepts cc ON cc.chunk_id=c.id
                            GROUP BY s.name ORDER BY n DESC"""):
        lines.append(f"- {r['name']}: {r['n']} distinct concepts")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return {"format": "md", "out": os.path.abspath(path), "bytes": os.path.getsize(path)}


def out_sqlite(db, path):
    """Clean standalone copy — other sqlite tooling gets the whole graph."""
    if os.path.abspath(path) == os.path.abspath(db.execute(
            "PRAGMA database_list").fetchall()[0]["file"]):
        sys.exit("FATAL: --out must differ from the source db")
    if os.path.exists(path):
        os.remove(path)
    db.execute("VACUUM INTO ?", (path,))
    return {"format": "sqlite", "out": os.path.abspath(path),
            "bytes": os.path.getsize(path)}


def out_package(db, outdir, title):
    """Self-contained share package, INGEST.md convention (MediaPlural/ingest):
    BLUF + load order + file map (with sizes + sha256) + fingerprint + the
    recipient-agent one-liner. Any agent — ours, Brandon's, a stranger's —
    reads INGEST.md and knows exactly how to absorb the corpus."""
    os.makedirs(outdir, exist_ok=True)
    stats = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
             for t in ["sources", "chunks", "concepts", "bridges"]}
    # 1. graph.json — the machine surface
    with open(os.path.join(outdir, "graph.json"), "w") as f:
        json.dump(graph_data(db), f, ensure_ascii=False)
    # 2. chunks.jsonl — the RAG-feed surface
    out_jsonl(db, os.path.join(outdir, "chunks.jsonl"), None, None)
    # 3. dossier.md — the human/LLM surface
    out_md(db, os.path.join(outdir, "dossier.md"))
    # 4. INGEST.md — the manifest
    file_map = []
    for fname in ["graph.json", "chunks.jsonl", "dossier.md"]:
        p = os.path.join(outdir, fname)
        file_map.append((fname, os.path.getsize(p)))
    # fingerprint: sha256 over the sorted file hashes, 16-hex (convention shape)
    h = hashlib.sha256()
    for fname, _ in sorted(file_map):
        with open(os.path.join(outdir, fname), "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    fp = h.hexdigest()[:16]
    bluf = (f"A consumable knowledge corpus: {stats['sources']} sources, "
            f"{stats['chunks']} chunks, {stats['concepts']} concepts, "
            f"{stats['bridges']} cross-source bridge concepts — vectorized "
            f"(deterministic 512-dim hashed embeddings), queryable, provenance-anchored.")
    lines = [f"# INGEST.md — machine manifest for {title}", "",
             "> Convention: MediaPlural/ingest — INGEST.md (canonical) / "
             "AGENT-INGEST.md (alias), one schema.",
             f"> **Package fingerprint (sha256):** `{fp}` — verify after "
             "transfer; if it differs, the tree changed.", "",
             "## Load order (the one required section)", "",
             "1. BLUF (below) — the one-paragraph bottom line.",
             "2. `graph.json` — the full graph (sources, chunks + vectors, "
             "concepts, links, bridges). The machine surface.",
             "3. `chunks.jsonl` — one chunk per line, denormalized for RAG "
             "loaders and vector stores.",
             "4. `dossier.md` — the human/LLM-readable summary: sources, "
             "bridges, strongest concept pairs.", "",
             "## BLUF", "", bluf, "", "## File map", ""]
    for fname, size in file_map:
        lines.append(f"- `{fname}` — {size:,} bytes")
    lines += ["", "## The one-liner", "",
              "**Prompt form:** Read `INGEST.md` at the package root and "
              "execute its load order; it routes everything else.",
              "**Load it:** drop `graph.json` into any tool that reads JSON, "
              "or `chunks.jsonl` into any JSONL/vector loader. The vectors are "
              "deterministic (same text = same vector, 512-dim, L2-normalized) "
              "— cosine similarity works with no model download.", "",
              "**Rebuild/extend:** the producing pipeline is "
              "github.com/MediaPlural/consumer (MIT): point it at any source "
              "(website, zip, gdrive, course) and it re-creates this package."]
    with open(os.path.join(outdir, "INGEST.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return {"format": "package", "out": os.path.abspath(outdir),
            "fingerprint": fp, "files": [f for f, _ in file_map] + ["INGEST.md"],
            "stats": stats}


def main():
    ap = argparse.ArgumentParser(description="Export the assimilated graph to any agent, tool, or db")
    ap.add_argument("db")
    ap.add_argument("--format", choices=["json", "jsonl", "csv", "md", "package", "sqlite"],
                    required=True)
    ap.add_argument("--out", default=None, help="output file (json/jsonl/md/sqlite)")
    ap.add_argument("--outdir", default=None, help="output dir (csv/package)")
    ap.add_argument("--title", default="knowledge corpus", help="package title")
    ap.add_argument("--source", default=None, help="filter: source name contains")
    ap.add_argument("--kind", default=None, help="filter: source kind")
    a = ap.parse_args()

    db = open_db(a.db)
    if a.format == "json":
        res = out_json(db, a.out or "consumer-graph.json", a.source, a.kind)
    elif a.format == "jsonl":
        res = out_jsonl(db, a.out or "consumer-chunks.jsonl", a.source, a.kind)
    elif a.format == "csv":
        res = out_csv(db, a.outdir or "consumer-csv", a.source, a.kind)
    elif a.format == "md":
        res = out_md(db, a.out or "consumer-dossier.md")
    elif a.format == "package":
        res = out_package(db, a.outdir or "consumer-package", a.title)
    elif a.format == "sqlite":
        res = out_sqlite(db, a.out or "consumer-copy.db")
    print(json.dumps({"ok": True, **res}, indent=2))


if __name__ == "__main__":
    main()