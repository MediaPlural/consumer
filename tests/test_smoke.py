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


def main():
    test_cli_shapes()
    test_srt_and_fingerprint()
    test_distiller()
    test_scrape_manifest()
    test_mcp_dispatch()
    test_course_dl_skool()
    test_author_and_explain()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()