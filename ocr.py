#!/usr/bin/env python3
"""consumer ocr — the image lane. needs_ocr flags become text, then knowledge.

ingest.py flags images (.png/.jpg/.webp/...) with needs_ocr. ocr.py consumes
those flags:

  macOS:   compiles ocr.swift (Vision framework / Live Text) once — genuinely
           local OCR, no API keys, no network. Cached at ~/.consumer/bin/.
  Linux:   tesseract if installed (documented, optional).
  None:    images stay flagged with a hint (never silently dropped).

After OCR, each image's text is written to the extracted dir and its
corpus.json entry is updated (needs_ocr cleared, extracted_to/chars set) so
the graph ingests it as a first-class source — screenshots, slides-as-images,
scanned pages, whiteboard photos all become queryable.

Usage:
  python3 ocr.py CORPUS_DIR          # OCR all needs_ocr files in a corpus
  python3 ocr.py --image FILE        # one image directly
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.expanduser("~/.consumer/bin")
HELPER = os.path.join(BIN_DIR, "consumer-ocr")
SWIFT_SRC = os.path.join(HERE, "ocr.swift")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".tiff", ".tif", ".bmp", ".heic")


def ensure_helper():
    """Compile the Vision helper once (cached by source mtime)."""
    if not os.path.isdir(BIN_DIR):
        os.makedirs(BIN_DIR, exist_ok=True)
    stale = (not os.path.exists(HELPER)) or (
        os.path.exists(SWIFT_SRC) and
        os.path.getmtime(SWIFT_SRC) > os.path.getmtime(HELPER))
    if stale:
        swiftc = shutil.which("swiftc")
        if not swiftc:
            return None
        r = subprocess.run([swiftc, "-O", SWIFT_SRC, "-o", HELPER],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return None
    return HELPER if os.path.exists(HELPER) else None


def tesseract_path():
    return shutil.which("tesseract")


def ocr_file(path, helper):
    """Return recognized text or None. Tries helper (macOS Vision), then
    tesseract; both absent -> None (image stays flagged, hint recorded)."""
    if helper:
        r = subprocess.run([helper, path], capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            return r.stdout.strip() or None
    t = tesseract_path()
    if t:
        r = subprocess.run([t, path, "stdout"], capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            return r.stdout.strip() or None
    return None


def main():
    ap = argparse.ArgumentParser(description="OCR lane: needs_ocr images -> text -> graph sources")
    ap.add_argument("corpus_dir", nargs="?", default=None,
                    help="a corpus dir (contains extracted/corpus.json) — OCR its flagged files")
    ap.add_argument("--image", default=None, help="OCR one image file directly")
    a = ap.parse_args()

    helper = ensure_helper()
    engine = "vision" if helper else ("tesseract" if tesseract_path() else None)
    if not engine:
        sys.exit("FATAL: no OCR engine — macOS needs Xcode's swiftc (Vision), "
                 "Linux needs tesseract installed")

    # direct image mode
    if a.image:
        text = ocr_file(a.image, helper)
        print(json.dumps({"ok": text is not None, "engine": engine,
                          "chars": len(text) if text else 0,
                          "text": (text or "")[:2000]}, ensure_ascii=False))
        return

    if not a.corpus_dir:
        sys.exit("FATAL: give a corpus dir or --image FILE")
    ex = os.path.join(a.corpus_dir, "extracted")
    cj = os.path.join(ex, "corpus.json")
    if not os.path.exists(cj):
        sys.exit(f"FATAL: {cj} not found — run ingest.py first")
    corpus = json.load(open(cj))

    done, no_text, skipped = 0, 0, 0
    for e in corpus["files"]:
        if not e.get("needs_ocr"):
            continue
        path = e["file"]
        if not os.path.exists(path) or os.path.splitext(path)[1].lower() not in IMAGE_EXT:
            skipped += 1
            continue
        text = ocr_file(path, helper)
        if not text:
            e["ocr_note"] = "no text detected (blank/photo-like image)"
            no_text += 1
            continue
        stem = re.sub(r"[^a-zA-Z0-9._-]", "_", e.get("rel") or os.path.basename(path))
        if stem.endswith(".txt"):
            stem = stem[:-4]
        tpath = os.path.join(ex, stem + ".txt")
        n = 1
        while os.path.exists(tpath):
            n += 1
            tpath = os.path.join(ex, f"{stem}.{n}.txt")
        with open(tpath, "w") as f:
            f.write(text)
        e["needs_ocr"] = False
        e["extracted_to"] = tpath
        e["chars"] = len(text)
        e["ocr_engine"] = engine
        e["ocr_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        done += 1

    with open(cj, "w") as f:
        json.dump(corpus, f, indent=2)
    print(json.dumps({"ok": True, "engine": engine, "ocr'd": done,
                      "no_text": no_text, "skipped": skipped,
                      "corpus": cj}, indent=2))


if __name__ == "__main__":
    main()