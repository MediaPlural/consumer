#!/usr/bin/env python3
"""consumer refine — clean, organize, structure, match the graph.

After ingest, real corpora are messy: near-duplicate chunks (the same page
acquired twice, boilerplate repeated), and exploded concepts ("affiliate",
"affiliates", "affiliate_" as separate rows). refine.py fixes the graph:

  dedup     near-identical chunks (cosine > 0.97) — keeps the earliest
  concepts  morphological merge: suffix-stemmed variants fold into one
            canonical concept ("affiliates" -> "affiliate"), tf summed
  report    what changed; --apply to write (dry-run default: honest)

Usage:
  python3 refine.py GRAPH.db [--apply]
"""
import argparse
import json
import os
import re
import sqlite3
import sys


def stem(w):
    """Tiny suffix stemmer (deterministic, stdlib): the point is folding
    morphological variants, not linguistic perfection."""
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "es", "ed", "ers", "er", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            base = w[: -len(suf)]
            if suf == "ies":
                base += "y"
            return base
    return w


def cosine(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def refine(db_path, apply):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    # --- 1. dedup near-identical chunks (per source) ---
    dups = []
    rows = [(r["id"], r["source_id"], json.loads(r["vector_json"]))
            for r in db.execute("SELECT id, source_id, vector_json FROM chunks ORDER BY source_id, idx")]
    by_src = {}
    for cid, sid, vec in rows:
        by_src.setdefault(sid, []).append((cid, vec))
    for sid, chunks in by_src.items():
        for i in range(len(chunks)):
            if chunks[i] is None:
                continue
            for j in range(i + 1, len(chunks)):
                if chunks[j] is None:
                    continue
                if cosine(chunks[i][1], chunks[j][1]) > 0.97:
                    dups.append(chunks[j][0])
                    chunks[j] = None
    # --- 2. concept morphological merge ---
    merges = []
    concepts = [(r["id"], r["phrase"]) for r in db.execute("SELECT id, phrase FROM concepts")]
    canon = {}
    for cid, phrase in concepts:
        s = stem(phrase.lower())
        if s in canon and s != phrase.lower():
            merges.append((cid, canon[s], phrase))
        else:
            canon[s] = cid

    report = {"near_duplicate_chunks": len(dups),
              "duplicate_example": None,
              "concept_merges": len(merges),
              "merge_examples": [f"'{p}' -> '{db.execute('SELECT phrase FROM concepts WHERE id=?', (keep,)).fetchone()[0]}'"
                                 for _, keep, p in merges[:5]],
              "mode": "applied" if apply else "dry-run (use --apply)"}
    if dups:
        r = db.execute("SELECT substr(text,1,60) FROM chunks WHERE id=?", (dups[0],)).fetchone()
        report["duplicate_example"] = r[0]

    if apply:
        # dedup: delete later duplicates + their concept rows
        if dups:
            marks = ",".join("?" * len(dups))
            db.execute(f"DELETE FROM chunk_concepts WHERE chunk_id IN ({marks})", dups)
            db.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({marks})", dups)
            db.execute(f"DELETE FROM chunks WHERE id IN ({marks})", dups)
        # concept merge: repoint chunk_concepts, sum tf, drop empty concepts
        for old, keep, _ in merges:
            merged = db.execute(
                "SELECT chunk_id, sum(tf) FROM chunk_concepts WHERE concept_id=? GROUP BY chunk_id",
                (old,)).fetchall()
            for chunk_id, tf in merged:
                db.execute(
                    "INSERT INTO chunk_concepts(chunk_id, concept_id, tf) VALUES(?,?,?) "
                    "ON CONFLICT DO UPDATE SET tf = tf + excluded.tf",
                    (chunk_id, keep, tf))
            db.execute("DELETE FROM chunk_concepts WHERE concept_id=?", (old,))
            db.execute("DELETE FROM concepts WHERE id=?", (old,))
        # rebuild derived tables
        db.execute("DELETE FROM concept_links")
        db.execute("DELETE FROM bridges")
        for a, b, co in db.execute("""
                SELECT cc1.concept_id a, cc2.concept_id b, count(*) co
                FROM chunk_concepts cc1 JOIN chunk_concepts cc2
                  ON cc1.chunk_id = cc2.chunk_id AND cc1.concept_id < cc2.concept_id
                GROUP BY a, b HAVING co >= 3""").fetchall()[:20000]:
            db.execute("INSERT INTO concept_links VALUES(?,?,?)", (a, b, co))
        for cid, n in db.execute("""
                SELECT cc.concept_id, count(DISTINCT c.source_id) n
                FROM chunk_concepts cc JOIN chunks c ON cc.chunk_id = c.id
                GROUP BY cc.concept_id HAVING n >= 2""").fetchall():
            db.execute("INSERT OR REPLACE INTO bridges VALUES(?,?)", (cid, n))
        db.commit()
        stats = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                 for t in ["chunks", "concepts", "bridges"]}
        report["after"] = stats
    print(json.dumps(report, indent=2))
    db.close()


def main():
    ap = argparse.ArgumentParser(description="Clean/organize/structure/match the graph: dedup + concept merge")
    ap.add_argument("db")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run report)")
    a = ap.parse_args()
    if not os.path.exists(a.db):
        sys.exit(f"FATAL: no graph at {a.db}")
    refine(a.db, a.apply)


if __name__ == "__main__":
    main()