#!/usr/bin/env python3
"""consumer distill — course corpus -> structured knowledge.

Input: a directory of transcripts (.txt/.json) + optional web text (.txt).
Output: concepts.json, keywords.json, course-map.md (in --out-dir).

The distiller runs a shallow local pass (frequency/rarity scoring, stdlib
only) so it never needs an API key; the squad's LLM layer sits downstream
of these files, not inside this script. This mirrors the ingest.md design
law: machine-readable first, cheap to adopt, expensive to rebuild.
"""
import argparse
import json
import math
import os
import re
import sys
from collections import Counter

STOP = set("""a an the and or but if then else for of to in on at by with from as is are was were be been being
this that these those it its we you your our their his her they them he she i me my mine do does did done
have has had will would can could should shall may might must not no nor so than too very just about into
over under out up down off again further once here there when where why how all any both each few more most
other some such only own same s t don now what which who whom whose because while during before after above
below between through around against got get gets go goes going make makes made way also like okay yeah um""".split())


def load_sources(in_dir):
    """Return list of {name, text, dur_s, seg_count} for each transcript.
    A .txt sitting next to its own .transcript.json is a derived file — skip it."""
    files = sorted(os.listdir(in_dir))
    json_stems = {f[:-len(".transcript.json")] for f in files if f.endswith(".transcript.json")}
    srcs = []
    for fname in files:
        path = os.path.join(in_dir, fname)
        if fname.endswith(".transcript.json"):
            try:
                d = json.load(open(path, errors="replace"))
                if "segments" in d or "text" in d:
                    segs = d.get("segments", [])
                    srcs.append({"name": fname, "text": d.get("text", ""),
                                 "dur_s": segs[-1]["end"] if segs else None,
                                 "segs": len(segs), "words": sum(len(s.get("words", [])) for s in segs)})
            except Exception:
                pass
        elif fname.endswith(".txt") and os.path.splitext(fname)[0] not in json_stems:
            srcs.append({"name": fname, "text": open(path, errors="replace").read(),
                         "dur_s": None, "segs": None, "words": None})
    if not srcs:
        sys.exit(f"FATAL: no .txt or .transcript.json files in {in_dir}")
    return srcs


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 1]


def score_keywords(texts):
    """Frequency x length x rarity scoring across the whole corpus."""
    doc_freq = Counter()
    term_freq = Counter()
    for text in texts:
        words = re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}", text.lower())
        seen = set()
        for w in words:
            if w in STOP or len(w) < 3:
                continue
            term_freq[w] += 1
            seen.add(w)
        for w in seen:
            doc_freq[w] += 1
    scored = []
    n = len(texts)
    for term, tf in term_freq.items():
        length_bonus = min(len(term), 10) / 10
        # Course doctrine: a term appearing across MANY lessons is core course
        # vocabulary (convergence = strongest signal) — so we BOOST document
        # convergence instead of penalizing it the way plain IDF does. Stop
        # words are already excluded; generic-in-any-corpus words score high
        # but the LLM layer refines downstream.
        convergence = doc_freq[term] / n if n else 0
        scored.append({"term": term, "tf": tf, "documents": doc_freq[term],
                       "score": round(tf * (0.5 + length_bonus) * (0.5 + convergence), 2)})
    scored.sort(key=lambda x: -x["score"])
    return scored


def extract_concepts(text):
    """Pattern-based concept extraction for spoken transcripts: capitalized
    multi-word phrases and definition patterns; falls back to bigrams that
    behave like terms (frequent, not stopword-led) for lowercase prose."""
    concepts = []
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", text):
        phrase = m.group(1)
        if phrase.lower().split()[0] not in STOP:
            concepts.append(phrase)
    PRONOUNISH = {"this", "that", "it", "there", "here", "these", "those", "he", "she",
                  "they", "we", "you", "i", "what", "which", "who", "one", "thing"}
    for m in re.finditer(r"\b([a-z][a-z'-]+(?:\s+[a-z][a-z'-]+)?)\s+(?:is|are|means|makes)\s+(?:a|an|the)\b", text, re.I):
        head = m.group(1).strip().lower().split()[0]
        if head not in PRONOUNISH:
            concepts.append(m.group(1).strip())
    # spoken prose is often uncapitalized; catch frequent content bigrams
    bigrams = Counter()
    for w1, w2 in re.findall(r"\b([a-z]{3,})\s+([a-z]{3,})\b", text.lower()):
        if w1 in STOP or w2 in STOP or w1 == w2:
            continue
        bigrams[f"{w1} {w2}"] += 1
    for phrase, count in bigrams.items():
        if count >= 2:
            concepts.append(phrase)
    return concepts


def main():
    ap = argparse.ArgumentParser(description="Course corpus -> concepts + keywords + map")
    ap.add_argument("in_dir", help="directory of transcripts (.txt / .transcript.json)")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--top-k", type=int, default=200)
    a = ap.parse_args()

    srcs = load_sources(a.in_dir)
    out_dir = a.out_dir or os.path.join(a.in_dir, "distilled")
    os.makedirs(out_dir, exist_ok=True)

    full_texts = [s["text"] for s in srcs]
    keywords = score_keywords(full_texts)[:a.top_k]

    all_text = "\n".join(full_texts)
    concept_counter = Counter(extract_concepts(all_text))
    concepts = [{"phrase": p, "count": c} for p, c in concept_counter.most_common(150)]

    # next-best-sentence seeds: highest-signal sentences (keyword density)
    kw_terms = {k["term"] for k in keywords[:60]}
    seeds = []
    for s in sentences(all_text)[:2000]:
        words = re.findall(r"[a-z']+", s.lower())
        if not words:
            continue
        density = sum(1 for w in words if w in kw_terms) / len(words)
        if density >= 0.20 and len(words) >= 6:
            seeds.append({"sentence": s[:300], "density": round(density, 2), "words": len(words)})
    seeds.sort(key=lambda x: -x["density"])
    seeds = seeds[:40]

    with open(os.path.join(out_dir, "keywords.json"), "w") as f:
        json.dump({"keywords": keywords}, f, indent=2)
    with open(os.path.join(out_dir, "concepts.json"), "w") as f:
        json.dump({"concepts": concepts}, f, indent=2)
    with open(os.path.join(out_dir, "next-best-seeds.json"), "w") as f:
        json.dump({"seeds": seeds}, f, indent=2)

    total_words = sum(len(s["text"].split()) for s in srcs)
    dur_total = sum(s["dur_s"] or 0 for s in srcs)
    lines = ["# Course Map", "",
             f"- Sources: {len(srcs)}", f"- Total words: {total_words}",
             f"- Total audio duration: {round(dur_total/60, 1)} min", "",
             "## Sources", ""]
    for s in srcs:
        d = f" ({round(s['dur_s']/60,1)} min)" if s.get("dur_s") else ""
        lines.append(f"- `{s['name']}`{d}")
    lines += ["", "## Top 30 keywords", ""]
    for k in keywords[:30]:
        lines.append(f"- **{k['term']}** — tf {k['tf']}, in {k['documents']}/{len(srcs)} sources, score {k['score']}")
    lines += ["", "## Named concepts", ""]
    for c in concepts[:30]:
        lines.append(f"- {c['phrase']} (x{c['count']})")
    lines += ["", "## Next-best-sentence seeds (high keyword density)", ""]
    for sd in seeds[:15]:
        lines.append(f"- density {sd['density']}: \"{sd['sentence'][:140]}\"")
    with open(os.path.join(out_dir, "course-map.md"), "w") as f:
        f.write("\n".join(lines) + "\n")

    print(json.dumps({"ok": True, "sources": len(srcs), "keywords": len(keywords),
                      "concepts": len(concepts), "seeds": len(seeds), "out_dir": out_dir}, indent=2))


if __name__ == "__main__":
    main()