#!/usr/bin/env python3
"""consumer author — create your own courses/works from scratch or from consumed knowledge.

The consumer loop closes here: knowledge goes IN (course-dl/transcribe/ingest/
distill) and knowledge comes OUT (authored courses, new editions, training
packages). Courses are one facet — the same scaffold fits playbooks, onboarding
guides, internal training, any structured knowledge work.

Commands:
  author.py new "Title" --out ./my-course --lessons 5
      Scaffold an empty authored course: course.json + lessons/*.md (each with
      objectives / core idea / body / key terms / self-check template).

  author.py from-corpus ./distilled --title "New Edition" --out ./edition
      Draft an authored course FROM consumed knowledge: concepts cluster into
      lesson drafts, the best seed sentences become each lesson's core idea,
      top keywords become key terms. A draft for human/agent editing — never
      presented as finished writing.

  author.py edit ./my-course
      (informational) prints where everything lives; edit the .md files, then
      rebuild the site with sitegen.py --lessons ./my-course/lessons.
"""
import argparse
import json
import os
import re
import sys
import time

LESSON_TEMPLATE = """# Lesson {n}: {title}

## Objectives
- (what the learner will be able to DO after this lesson)

## Core idea
{core}

## Body
{body}

## Key terms
{terms}

## Check yourself
- Q: (one question whose answer proves the objective)
"""


def write_course_json(out, title, lessons):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "course.json"), "w") as f:
        json.dump({
            "title": title, "status": "draft",
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "lessons": lessons,
            "provenance": {"author": "consumer author.py"},
        }, f, indent=2)


def cmd_new(title, out, n):
    lessons = []
    for i in range(1, n + 1):
        fname = f"lesson-{i:02d}.md"
        path = os.path.join(out, "lessons", fname)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(LESSON_TEMPLATE.format(
                n=i, title=f"(draft title for lesson {i})",
                core="(the one sentence this lesson exists to teach)",
                body="(two to four short paragraphs. Plain language, one idea per sentence.)",
                terms="- (term — what it means here)"))
        lessons.append(fname)
    write_course_json(out, title, lessons)
    print(json.dumps({"ok": True, "cmd": "new", "out": os.path.abspath(out),
                      "lessons": lessons,
                      "next": f"python3 sitegen.py <distilled-dir> --lessons {out}/lessons --title '{title}'"},
                     indent=2))


def load_corpus(distilled):
    def j(name):
        p = os.path.join(distilled, name)
        return json.load(open(p)) if os.path.exists(p) else {}
    return (j("concepts.json").get("concepts", []),
            j("keywords.json").get("keywords", []),
            j("next-best-seeds.json").get("seeds", []))


def cluster(concepts, n):
    """Chunk concept list into n lesson-sized clusters (order preserved).
    Thin corpora pad with empty clusters — the requested lesson count is the
    contract; lesson drafts with no concepts still get scaffolds + seeds."""
    if not concepts:
        return [[] for _ in range(n)]
    per = max(1, -(-len(concepts) // n))
    chunks = [concepts[i:i + per] for i in range(0, len(concepts), per)][:n]
    while len(chunks) < n:
        chunks.append([])
    return chunks


def pick_core(seed_text, concepts_in_lesson):
    """The seed sentence with most keyword overlap with this lesson's concepts.
    Drafts are anchored to the corpus's own strongest sentences."""
    cterms = " ".join(concepts_in_lesson).lower()
    best, score = None, -1
    for s in seed_text:
        words = set(re.findall(r"[a-z']+", s["sentence"].lower()))
        hit = sum(1 for w in words if w in cterms)
        if hit > score:
            best, score = s["sentence"], hit
    return best or "(write the core idea)"


def cmd_from_corpus(distilled, title, out, n):
    concepts, keywords, seeds = load_corpus(distilled)
    if not concepts and not seeds:
        sys.exit(f"FATAL: no concepts/seeds in {distilled} — run distill.py first")
    clusters = cluster(concepts, n)
    kws = [k["term"] for k in keywords]
    lessons = []
    for i, cl in enumerate(clusters, 1):
        core = pick_core(seeds, [c["phrase"] for c in cl])
        terms = "\n".join(f"- **{c['phrase']}** — (define in your words)" for c in cl[:5]) \
            or f"- **{kws[0]}** — (define in your words)" if kws else "- (add key terms)"
        body = "(expand the core idea: why it is true, how to apply it, one concrete example.)"
        fname = f"lesson-{i:02d}.md"
        path = os.path.join(out, "lessons", fname)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(LESSON_TEMPLATE.format(
                n=i, title=(cl[0]["phrase"].title() if cl else f"Lesson {i}"),
                core=core, body=body, terms=terms))
        lessons.append(fname)
    write_course_json(out, title, lessons)
    print(json.dumps({"ok": True, "cmd": "from-corpus", "out": os.path.abspath(out),
                      "lessons": lessons, "drafted_from": os.path.abspath(distilled),
                      "note": "DRAFT output — edit the .md files, they are the source of truth"},
                     indent=2))


def cmd_edit(path):
    cj = os.path.join(path, "course.json")
    if not os.path.exists(cj):
        sys.exit(f"FATAL: {cj} not found — is this an authored course dir?")
    d = json.load(open(cj))
    print(f"Course: {d['title']} ({d['status']}) — {len(d['lessons'])} lessons")
    print(f"Edit the markdown directly:")
    for l in d["lessons"]:
        print(f"  {os.path.join(path, 'lessons', l)}")
    print(f"Rebuild the site:\n  python3 sitegen.py <distilled-dir> --lessons {path}/lessons --title '{d['title']}'")


def main():
    ap = argparse.ArgumentParser(description="Create authored courses from scratch or from consumed knowledge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("new", help="scaffold an empty authored course")
    p1.add_argument("title"); p1.add_argument("--out", required=True)
    p1.add_argument("--lessons", type=int, default=5)
    p2 = sub.add_parser("from-corpus", help="draft an authored course from a distilled corpus")
    p2.add_argument("distilled"); p2.add_argument("--title", required=True)
    p2.add_argument("--out", required=True)
    p2.add_argument("--lessons", type=int, default=5)
    p3 = sub.add_parser("edit", help="where everything lives in an authored course")
    p3.add_argument("path")
    a = ap.parse_args()
    if a.cmd == "new":
        cmd_new(a.title, a.out, a.lessons)
    elif a.cmd == "from-corpus":
        cmd_from_corpus(a.distilled, a.title, a.out, a.lessons)
    elif a.cmd == "edit":
        cmd_edit(a.path)


if __name__ == "__main__":
    main()