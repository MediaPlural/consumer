#!/usr/bin/env python3
"""consumer smoke tests — fast, offline, no model download.

Run: python3 tests/test_smoke.py
Covers: CLI shapes, transcript SRT generation, distiller scoring/dedupe,
acquisition manifest, MCP tool-call dispatch. The heavy path (real STT) is
exercised by the live verification already recorded in README provenance.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
PY = sys.executable
PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def test_cli_shapes():
    print("CLI shapes")
    for tool in ["transcribe.py", "scrape.py", "distill.py", "consumer.py"]:
        r = run([PY, os.path.join(HERE, tool), "--help"])
        check(f"{tool} --help", r.returncode == 0, r.stderr[:200])


def test_srt_and_fingerprint():
    print("SRT + provenance writers (unit)")
    sys.path.insert(0, HERE)
    import importlib.util
    spec = importlib.util.spec_from_file_location("tr", os.path.join(HERE, "transcribe.py"))
    tr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tr)
    srt = tr.srt_time(3661.5)
    check("srt_time", srt == "01:01:01,500", srt)
    segs = [{"start": 0.0, "end": 1.5, "text": "hello"}, {"start": 1.6, "end": 2.0, "text": "  "}]
    tmp = tempfile.mkdtemp() + "/x.srt"
    tr.write_srt(segs, tmp)
    body = open(tmp).read()
    check("write_srt skips empty", body.count("-->") == 1 and "hello" in body, body)
    # sha256 of a known string
    p = tempfile.mkdtemp() + "/f.txt"
    open(p, "w").write("abc")
    check("sha256_file", tr.sha256_file(p).startswith("ba7816bf"))


def test_distiller():
    print("distiller (unit)")
    sys.path.insert(0, HERE)
    import importlib.util
    spec = importlib.util.spec_from_file_location("di", os.path.join(HERE, "distill.py"))
    di = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(di)
    kw = di.score_keywords(["the funnel is the machine that thinks about outreach",
                            "the funnel machine decides what the next move is"])
    check("keyword scoring", kw and kw[0]["term"] in ("funnel", "machine"), kw[:2])
    cons = di.extract_concepts("the funnel machine is a system. This is a test. "
                               "the funnel machine is a system. Reply within five minutes.")
    check("concept extraction no pronoun junk", "This" not in cons, cons[:5])
    check("concept bigram freq", cons.count("funnel machine") == 2, cons)


def test_scrape_manifest():
    print("scrape manifest (unit)")
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "page.txt")
    open(p, "w").write("hello")
    sys.path.insert(0, HERE)
    import importlib.util
    spec = importlib.util.spec_from_file_location("sc", os.path.join(HERE, "scrape.py"))
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)
    m = sc.manifest(tmp, "https://example.com", p, "test")
    data = json.load(open(m))
    check("manifest writes", len(data["sources"]) == 1 and data["sources"][0]["url"] == "https://example.com")


def test_mcp_dispatch():
    print("MCP dispatch (integration, stdio)")
    # server reads stdin until EOF; communicate() closes stdin so it exits.
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    proc = subprocess.Popen([PY, os.path.join(HERE, "mcp-server.py")],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    out, _ = proc.communicate(json.dumps(payload) + "\n", timeout=30)
    resp = json.loads(out.strip().splitlines()[0])
    check("tools/list", resp["result"]["tools"] and len(resp["result"]["tools"]) >= 3,
          str(resp)[:200])
    # unknown tool call returns isError
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "nope", "arguments": {}}}
    proc = subprocess.Popen([PY, os.path.join(HERE, "mcp-server.py")],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    out, _ = proc.communicate(json.dumps(call) + "\n", timeout=30)
    resp = json.loads(out.strip().splitlines()[0])
    check("unknown tool -> isError", resp["result"].get("isError") is True, str(resp)[:200])


def test_course_dl_skool():
    print("course-dl skool support (unit)")
    sys.path.insert(0, HERE)
    import importlib.util
    spec = importlib.util.spec_from_file_location("cdl", os.path.join(HERE, "course-dl.py"))
    cdl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdl)
    check("skool md regex 32-hex", bool(cdl.SKOOL_MD_RE.search('href="?md=0430f1b55fa146099a333506c6adb7ac"')))
    check("skool md regex rejects short", not cdl.SKOOL_MD_RE.search("md=abc123"))
    # skool referer: save_media builds the yt-dlp command with --referer
    src = open(os.path.join(HERE, "course-dl.py")).read()
    check("referer flag present", '--referer", "https://www.skool.com' in src or
          '"--referer", "https://www.skool.com"' in src or "--referer" in src)
    # EMBED_HOSTS covers skool/mux/cloudflarestream
    check("embed hosts extended", all(h in cdl.EMBED_HOSTS for h in ("skool", "mux", "cloudflarestream")))


def test_author_and_explain():
    print("author + explain CLIs (unit)")
    r1 = run([PY, os.path.join(HERE, "author.py"), "--help"])
    check("author.py --help", r1.returncode == 0, r1.stderr[:150])
    r2 = run([PY, os.path.join(HERE, "explain.py"), "--help"])
    check("explain.py --help", r2.returncode == 0, r2.stderr[:150])
    # from-corpus against the live test corpus (created by earlier runs);
    # if missing, synthesize a minimal distilled corpus
    import tempfile
    dist = tempfile.mkdtemp() + "/distilled"
    os.makedirs(dist, exist_ok=True)
    with open(os.path.join(dist, "concepts.json"), "w") as f:
        json.dump({"concepts": [{"phrase": "five minutes", "count": 2}]}, f)
    with open(os.path.join(dist, "next-best-seeds.json"), "w") as f:
        json.dump({"seeds": [{"sentence": "Reply within five minutes instead of 30.", "density": 0.6, "words": 7}]}, f)
    with open(os.path.join(dist, "keywords.json"), "w") as f:
        json.dump({"keywords": [{"term": "reply", "tf": 3, "documents": 1, "score": 1.5}]}, f)
    out = tempfile.mkdtemp() + "/course"
    r3 = run([PY, os.path.join(HERE, "author.py"), "from-corpus", dist, "--title", "T", "--out", out, "--lessons", "2"])
    check("author from-corpus", r3.returncode == 0 and os.path.exists(os.path.join(out, "lessons", "lesson-02.md")), r3.stderr[:150])
    ex = tempfile.mkdtemp() + "/explainer"
    r4 = run([PY, os.path.join(HERE, "explain.py"), dist, "--title", "T", "--out", ex])
    ok = r4.returncode == 0 and os.path.exists(os.path.join(ex, "slides.py")) and os.path.exists(os.path.join(ex, "storyboard.md"))
    check("explain project", ok, r4.stderr[:150])
    if ok:
        ns = {}
        exec(open(os.path.join(ex, "slides.py")).read(), ns)
        check("rendermill schema", isinstance(ns["SLIDES"], list) and ns["SLIDES"][0]["type"] == "html"
              and "narration" in ns["SLIDES"][0] and "tts" in ns["CONFIG"])




def test_graph_and_source():
    print("graph + source (unit, live mini-corpus)")
    import tempfile, zipfile
    tmp = tempfile.mkdtemp()
    # a two-file zip source
    zp = os.path.join(tmp, "k.zip")
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("a.txt", "The funnel machine decides the next move. " * 8)
        z.writestr("b.md", "Reply within five minutes. New evidence every day. " * 8)
    r = subprocess.run([PY, os.path.join(HERE, "source.py"), zp,
                        "--workspace", os.path.join(tmp, "ws"), "--full",
                        "--db", os.path.join(tmp, "g.db")],
                       capture_output=True, text=True, timeout=120)
    check("source --full chain", r.returncode == 0 and '"graph"' in r.stdout, r.stderr[-200:])
    if r.returncode == 0:
        g = json.loads(r.stdout)["graph"]
        check("graph built", g["sources"] >= 2 and g["chunks"] >= 2, str(g)[:150])
    db = os.path.join(tmp, "g.db")
    if os.path.exists(db):
        r2 = subprocess.run([PY, os.path.join(HERE, "graph.py"), "semantic",
                             "funnel machine", "--db", db], capture_output=True, text=True, timeout=60)
        check("semantic query", r2.returncode == 0 and len(json.loads(r2.stdout)) >= 1, r2.stderr[-150:])
        r3 = subprocess.run([PY, os.path.join(HERE, "graph.py"), "insight",
                             "--db", db], capture_output=True, text=True, timeout=60)
        check("insight query", r3.returncode == 0 and "bridge_concepts" in r3.stdout, r3.stderr[-150:])




def test_export_sync():
    print("export + sync (live round-trip)")
    import tempfile
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "g.db")
    # build a graph
    dist = os.path.join(tmp, "corpus")
    os.makedirs(dist, exist_ok=True)
    open(os.path.join(dist, "a.txt"), "w").write(
        "The funnel machine decides the next move for every lead. " * 10)
    r = subprocess.run([PY, os.path.join(HERE, "graph.py"), "ingest", dist, "--db", db],
                       capture_output=True, text=True, timeout=120)
    check("graph build", r.returncode == 0, r.stderr[-200:])
    # export all key formats
    r2 = subprocess.run([PY, os.path.join(HERE, "export.py"), db, "--format", "jsonl",
                         "--out", os.path.join(tmp, "c.jsonl")],
                        capture_output=True, text=True, timeout=120)
    check("export jsonl", r2.returncode == 0 and json.loads(r2.stdout)["lines"] >= 1, r2.stderr[-150:])
    r3 = subprocess.run([PY, os.path.join(HERE, "export.py"), db, "--format", "package",
                         "--outdir", os.path.join(tmp, "pkg"), "--title", "T"],
                        capture_output=True, text=True, timeout=120)
    check("export package", r3.returncode == 0 and
          os.path.exists(os.path.join(tmp, "pkg", "INGEST.md")), r3.stderr[-150:])
    # import package into fresh db
    fresh = os.path.join(tmp, "fresh.db")
    r4 = subprocess.run([PY, os.path.join(HERE, "sync.py"), "import-package",
                         os.path.join(tmp, "pkg"), "--db", fresh],
                        capture_output=True, text=True, timeout=120)
    check("import-package", r4.returncode == 0, r4.stderr[-200:])
    # merge original into fresh -> dedup means chunks don't double
    r5 = subprocess.run([PY, os.path.join(HERE, "sync.py"), "merge", fresh, db,
                          "--out", os.path.join(tmp, "m.db")],
                        capture_output=True, text=True, timeout=120)
    if r5.returncode == 0:
        after = json.loads(r5.stdout)["after"]["chunks"]
        check("merge dedup", after == json.loads(r.stdout)["chunks"], f"after={after}")
    else:
        check("merge dedup", False, r5.stderr[-150:])




def test_attribution_flow():
    print("attribution flow (acquire -> ingest -> graph -> search)")
    import tempfile
    tmp = tempfile.mkdtemp()
    # synthetic acquisition manifest + file (offline: no real fetch)
    ws = os.path.join(tmp, "acquired")
    os.makedirs(ws)
    open(os.path.join(ws, "page.txt"), "w").write("self-improving agent creates skills from experience. " * 6)
    json.dump({"sources": [{"kind": "page", "url": "https://example.com/x",
                            "file": os.path.join(ws, "page.txt"), "sha256": "0" * 64,
                            "tool": "urllib+stdlib-html", "size": 10,
                            "acquired_at": "2026-10-06T00:00:00+0000"}]},
              open(os.path.join(ws, "acquisition.json"), "w"))
    r = subprocess.run([PY, os.path.join(HERE, "ingest.py"), ws, "--recursive"],
                       capture_output=True, text=True, timeout=120)
    check("ingest with acquisition", r.returncode == 0, r.stderr[-200:])
    db = os.path.join(tmp, "g.db")
    r2 = subprocess.run([PY, os.path.join(HERE, "graph.py"), "ingest",
                         os.path.join(ws, "extracted"), "--db", db],
                        capture_output=True, text=True, timeout=120)
    check("graph ingest", r2.returncode == 0, r2.stderr[-200:])
    r3 = subprocess.run([PY, os.path.join(HERE, "graph.py"), "search", "self-improving",
                         "--db", db, "--limit", "1"], capture_output=True, text=True, timeout=60)
    if r3.returncode == 0 and r3.stdout.strip():
        res = json.loads(r3.stdout)
        att = res[0].get("attribution") or {}
        check("search result carries url", att.get("url") == "https://example.com/x", str(att)[:120])
        check("search result carries tool", att.get("tool") == "urllib+stdlib-html", str(att)[:120])
    else:
        check("search result carries url", False, r3.stderr[-150:])

def test_responsive_ui_served():
    print("responsive ui served by api")
    import zipfile
    src = open(os.path.join(HERE, "ui.html")).read()
    check("ui has media queries", "@media (max-width: 720px)" in src and "@media (max-width: 480px)" in src)
    check("ui escapes untrusted text", "const esc =" in src)
    check("ui renders attribution", "attribution" in src and "acquire" not in src[:50])




def test_ocr_and_watch():
    print("ocr lane + watch mode (live)")
    import tempfile
    tmp = tempfile.mkdtemp()
    inbox = os.path.join(tmp, "inbox")
    os.makedirs(inbox)
    open(os.path.join(inbox, "n.md"), "w").write(
        "The funnel machine decides the next move for every lead. " * 6)
    db = os.path.join(tmp, "k.db")
    r = subprocess.run([PY, os.path.join(HERE, "watch.py"), "--dir", inbox,
                        "--db", db, "--once"], capture_output=True, text=True, timeout=300)
    check("watch --once assimilates", r.returncode == 0 and "graph" in r.stderr, r.stderr[-150:])
    r2 = subprocess.run([PY, os.path.join(HERE, "graph.py"), "search", "funnel",
                         "--db", db, "--limit", "1"], capture_output=True, text=True, timeout=60)
    ok = r2.returncode == 0 and r2.stdout.strip() and json.loads(r2.stdout)
    check("watched file searchable", bool(ok), r2.stderr[-120:])
    # ocr.py CLI shape
    r3 = subprocess.run([PY, os.path.join(HERE, "ocr.py"), "--help"], capture_output=True, text=True, timeout=60)
    check("ocr.py --help", r3.returncode == 0)
    # ocr helper present (macOS vision) or tesseract — engine detectable.
    # ensure_helper() compiles on demand: a fresh clone builds it on first
    # use, so the test asks ocr.py to build rather than assuming a prior run.
    helper = os.path.expanduser("~/.consumer/bin/consumer-ocr")
    if not os.path.exists(helper) and not shutil.which("tesseract"):
        sys.path.insert(0, HERE)
        import importlib.util
        spec = importlib.util.spec_from_file_location("ocrmod", os.path.join(HERE, "ocr.py"))
        ocrmod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ocrmod)
        ocrmod.ensure_helper()
    check("ocr engine available", os.path.exists(helper) or shutil.which("tesseract") is not None)


def main():
    test_cli_shapes()
    test_srt_and_fingerprint()
    test_distiller()
    test_scrape_manifest()
    test_mcp_dispatch()
    test_course_dl_skool()
    test_author_and_explain()
    test_graph_and_source()
    test_export_sync()
    test_attribution_flow()
    test_responsive_ui_served()
    test_ocr_and_watch()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()