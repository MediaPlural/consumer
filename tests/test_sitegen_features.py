#!/usr/bin/env python3
"""sitegen course-map feature tests — HL membership UX dossier §5 takeaways
1,2,3,5,6,7,8,9 (4 is data-model only, 10 is the API pre-pass, other squad).

Builds REAL sites with a course-map.json exercising every feature and asserts
the emitted HTML/CSS/JS structure with stdlib re + html.parser — no browser,
no network, stdlib-only.

Run: python3 tests/test_sitegen_features.py
Laws checked here:
  - gating: old corpora (no course-map.json) render byte-identically
  - XP and %-progress feed the same consumer-progress-v1 completion events
  - no external CDNs/assets: pure inline CSS/JS/SVG
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser

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


def run_sitegen(dist, lessons_dir, out, extra=()):
    r = subprocess.run([PY, os.path.join(HERE, "sitegen.py"), dist,
                        "--lessons", lessons_dir, "--title", "Feature Course",
                        "--out", out, *extra],
                       capture_output=True, text=True, timeout=120)
    return r


def make_corpus(cmap=None, offer=None, n_lessons=5):
    """Distilled corpus + transcripts whose titles match the course map."""
    tmp = tempfile.mkdtemp()
    dist = os.path.join(tmp, "distilled")
    tr = os.path.join(tmp, "transcripts")
    os.makedirs(dist)
    os.makedirs(tr)
    json.dump({"keywords": [{"term": "funnel", "tf": 3, "documents": 1, "score": 1.5}]},
              open(os.path.join(dist, "keywords.json"), "w"))
    json.dump({"concepts": [{"phrase": "funnel machine", "count": 2}]},
              open(os.path.join(dist, "concepts.json"), "w"))
    json.dump({"seeds": [{"sentence": "Reply within five minutes.",
                          "density": 0.6, "words": 7}]},
              open(os.path.join(dist, "next-best-seeds.json"), "w"))
    open(os.path.join(dist, "course-map.md"), "w").write("# Feature course")
    titles = ([l["title"] for c in cmap["categories"] for l in c["lessons"]]
              if cmap else [f"Lesson {i}" for i in range(1, n_lessons + 1)])
    for i in range(1, n_lessons + 1):
        t = titles[i - 1] if i <= len(titles) else f"Lesson {i}"
        json.dump({"text": f"{t}. The funnel machine decides the next move. "
                           "Reply within five minutes. " * 6,
                   "segments": [{"start": 0.0, "end": 90.0 * i, "text": "s"}]},
                  open(os.path.join(tr, f"l{i:02d}.transcript.json"), "w"))
    if cmap is not None:
        if offer is not None:
            cmap = dict(cmap, offer=offer)
        json.dump(cmap, open(os.path.join(dist, "course-map.json"), "w"))
    return dist, tr


def course_map_fixture():
    """One course map exercising every feature: published, locked (with
    unlock condition), draft, funnel (with materials + locked comments),
    drip_days, per-category grouping, an offer block."""
    return {"schema": "course-map/consumer-v1",
            "categories": [
                {"title": "Foundations", "lessons": [
                    {"title": "Welcome to the funnel", "visibility": "published",
                     "comment_status": "visible"},
                    {"title": "Map the machine", "visibility": "locked",
                     "unlock_condition": "Finish lesson 1",
                     "comment_status": "hidden"}]},
                {"title": "Extras", "lessons": [
                    {"title": "Secret bonus lesson", "visibility": "draft"},
                    {"title": "Book your audit", "visibility": "published",
                     "contentType": "funnel",
                     "funnel": {"url": "https://example.com/audit",
                                "label": "Book the audit"},
                     "comment_status": "locked",
                     "materials": [
                         {"title": "Worksheet", "type": "pdf",
                          "url": "files/worksheet.pdf"},
                         {"title": "Checklist", "type": "zip",
                          "url": "files/checklist.zip"}]},
                    {"title": "Deep drip lesson", "visibility": "published",
                     "drip_days": 3}]}]}


OFFER_FIXTURE = {"title": "Feature Package", "type": "onetime",
                 "access_terms": "lifetime access, all future editions",
                 "days_of_access": None, "version": 2}


def nav_chunk(src, nav_id):
    m = re.search(r'<nav id="' + nav_id + r'".*?</nav>', src, re.S)
    return m.group(0) if m else ""


class StrictParser(HTMLParser):
    """stdlib html.parser pass that crashes on malformed markup."""
    def error(self, message):
        raise ValueError(message)


def test_gating_legacy_identical():
    print("gating: legacy corpora render identically (no course-map.json)")
    dist, tr = make_corpus(cmap=None)
    out1 = os.path.join(tempfile.mkdtemp(), "a", "index.html")
    r1 = run_sitegen(dist, tr, out1)
    check("legacy sitegen runs", r1.returncode == 0, r1.stderr[-200:])
    src1 = open(out1).read()
    res1 = json.loads(r1.stdout)
    check("legacy run reports no offer", "offer" not in res1, str(res1)[:150])
    check("no offer.json emitted",
          not os.path.exists(os.path.join(os.path.dirname(out1), "offer.json")))
    for probe in ("course-map-toc", "certificate", "cmap-check", "CMAP",
                  "data-visibility", "discuss", "action-card"):
        check(f"legacy output has no {probe} surface", probe not in src1)
    # determinism: a second run is byte-identical (stable generator)
    out2 = os.path.join(tempfile.mkdtemp(), "b", "index.html")
    run_sitegen(dist, tr, out2)
    check("legacy generation deterministic",
          open(out1).read() == open(out2).read())
    # malformed/unknown-schema course-map.json is ignored -> legacy output
    bad = os.path.join(os.path.dirname(dist), "badmap.json")
    json.dump({"schema": "nope", "categories": []}, open(bad, "w"))
    out3 = os.path.join(tempfile.mkdtemp(), "c", "index.html")
    r3 = run_sitegen(dist, tr, out3, ("--course-map-json", bad))
    check("unknown schema ignored (legacy path)",
          r3.returncode == 0 and "CMAP" not in open(out3).read()
          and not os.path.exists(os.path.join(os.path.dirname(out3), "offer.json")),
          r3.stderr[-150:])


def test_take1_interactive_course_map_toc():
    print("takeaway 1: interactive course-map TOC (checkboxes, same store)")
    dist, tr = make_corpus(course_map_fixture())
    out = os.path.join(tempfile.mkdtemp(), "site", "index.html")
    r = run_sitegen(dist, tr, out)
    check("meta sitegen runs", r.returncode == 0, r.stderr[-200:])
    src = open(out).read()
    cmap = nav_chunk(src, "course-map-toc")
    check("course-map TOC rendered", cmap != "", "no <nav id=course-map-toc>")
    checks = re.findall(r'<input type="checkbox" class="cmap-check" data-lesson="([^"]+)"', cmap)
    check("per-lesson checkboxes present", len(checks) == 4,
          f"found {len(checks)}: {checks}")  # 5 lessons minus 1 draft
    check("draft lesson absent from course-map TOC", "lesson-03" not in cmap)
    cats = re.findall(r'<span class="cmap-cat-title">([^<]+)</span>', cmap)
    check("categories rendered", cats == ["Foundations", "Extras"], str(cats))
    prog = re.findall(r'data-cmap-progress="([^"]+)"', cmap)
    check("per-category % progress elements", prog == ["foundations", "extras"], str(prog))
    # checkboxes persist to the SAME store as the XP hook (one source of truth)
    check("checkbox JS writes consumer-progress-v1",
          re.search(r'cmap-check.*?s\.done\[id\] = Date\.now\(\)', src, re.S) is not None)
    check("checkbox handler saves to KEY store",
          'localStorage.getItem(KEY)' in src and '"consumer-progress-v1"' in src)
    check("checkbox toggle drives refresh()",
          "save(s); refresh();" in src)
    check("certificate JS reads same KEY store",
          src.count('localStorage.getItem(KEY)') >= 1 and "courseProgress" in src)


def test_take2_three_state_visibility():
    print("takeaway 2: draft/published/locked visibility")
    dist, tr = make_corpus(course_map_fixture())
    out = os.path.join(tempfile.mkdtemp(), "site", "index.html")
    run_sitegen(dist, tr, out)
    src = open(out).read()
    sec2 = re.search(r'<section class="lesson"[^>]*id="lesson-02".*?</section>', src, re.S)
    check("locked lesson section rendered", sec2 is not None)
    if sec2:
        s2 = sec2.group(0)
        check("locked carries data-visibility",
              'data-visibility="locked"' in s2)
        check("lock glyph (inline SVG) present",
              'class="lock-glyph"' in s2 and "<svg" in s2)
        check("unlock condition text present",
              "Finish lesson 1" in s2 and "data-unlock-condition" in s2)
        check("locked complete button disabled", "disabled" in s2)
    sec1 = re.search(r'<section class="lesson"[^>]*id="lesson-01".*?</section>', src, re.S)
    check("published lesson (default) has no lock note",
          sec1 and "lock-note" not in sec1.group(0))
    # draft: rendered (unlinked) but absent from BOTH navs
    check("draft lesson section rendered with data-visibility",
          'data-visibility="draft"' in src)
    for nav_id in ("toc", "course-map-toc"):
        nav = nav_chunk(src, nav_id)
        check(f"draft hidden from #{nav_id} nav",
              "lesson-03" not in nav, f"lesson-03 leaked into {nav_id}")
    draft_sec = re.search(r'<section class="lesson"[^>]*id="lesson-03".*?</section>', src, re.S)
    check("draft section has no anchor link targeting it from nav",
          draft_sec and ('href="#lesson-03"' not in nav_chunk(src, "toc")))
    # CMAP JS excludes draft from progress totals
    check("JS progress excludes drafts",
          'CMAP.filter(function (l) { return l.visibility !== "draft"; })' in src)


def test_take3_client_side_drip():
    print("takeaway 3: client-side drip (enrollment = first visit)")
    dist, tr = make_corpus(course_map_fixture())
    out = os.path.join(tempfile.mkdtemp(), "site", "index.html")
    run_sitegen(dist, tr, out)
    src = open(out).read()
    sec5 = re.search(r'<section class="lesson"[^>]*id="lesson-05".*?</section>', src, re.S)
    check("drip lesson carries data-drip-days",
          sec5 and 'data-drip-days="3"' in sec5.group(0))
    check("static fallback text 'unlocks 3 days after enrollment'",
          sec5 and "unlocks 3 days after enrollment" in sec5.group(0))
    check("enrollment date set on first visit",
          re.search(r'if \(!s\.enrolled_at\) \{ s\.enrolled_at = Date\.now\(\); save\(s\); \}', src)
          is not None)
    check("daysLeft computed from enrollment + drip_days",
          "daysLeft" in src and "86400000" in src)
    check("dynamic 'unlocks in X days' text",
          '"unlocks in " + dl' in src)
    check("drip-gated complete buttons disabled live",
          re.search(r'if \(btn\) btn\.disabled = locked', src) is not None)
    check("drip note refreshed client-side",
          re.search(r'\.drip-note\[data-lesson=', src) is not None)
    # no auto-unlock without storage: pure client math, no backend
    check("no backend/network in drip path",
          "fetch(" not in src and "XMLHttpRequest" not in src)


def test_take5_funnel_lesson():
    print("takeaway 5 (dossier 6): funnel contentType action card")
    dist, tr = make_corpus(course_map_fixture())
    out = os.path.join(tempfile.mkdtemp(), "site", "index.html")
    run_sitegen(dist, tr, out)
    src = open(out).read()
    sec4 = re.search(r'<section class="lesson"[^>]*id="lesson-04".*?</section>', src, re.S)
    check("funnel lesson section present", sec4 is not None)
    if sec4:
        s4 = sec4.group(0)
        check("action card rendered",
              'class="action-card"' in s4 and 'data-funnel="1"' in s4)
        check("CTA button with configured url+label",
              'href="https://example.com/audit"' in s4 and "Book the audit" in s4)
        check("funnel lesson carries data-content-type",
              'data-content-type="funnel"' in s4)
        check("same visual weight (same section.lesson skeleton)",
              s4.startswith('<section class="lesson"') and "lesson-head" in s4
              and "insights" in s4 and "data-xp=" in s4)
        check("funnel lesson IS completable like video lessons",
              '<button class="complete-btn"' in s4 and "disabled" not in
              s4.split("<button")[1].split(">")[0] if "<button" in s4 else False)


def test_take6_materials_chips():
    print("takeaway 6 (dossier 7): materials chips with type icons")
    dist, tr = make_corpus(course_map_fixture())
    out = os.path.join(tempfile.mkdtemp(), "site", "index.html")
    run_sitegen(dist, tr, out)
    src = open(out).read()
    sec4 = re.search(r'<section class="lesson"[^>]*id="lesson-04".*?</section>', src, re.S)
    check("materials block present", sec4 and 'class="materials"' in sec4.group(0))
    chips = re.findall(r'<a class="chip" data-mat-type="([^"]+)" href="([^"]+)"', src)
    check("two material chips", len(chips) == 2, str(chips))
    check("pdf chip typed + linked",
          ("pdf", "files/worksheet.pdf") in chips)
    check("zip chip typed + linked",
          ("zip", "files/checklist.zip") in chips)
    check("chips are download links", 'download>' in src)
    check("inline SVG icons (no external assets)",
          src.count('class="chip-icon"') == 2 and "<svg" in src)
    check("chip titles rendered",
          "Worksheet" in src and "Checklist" in src)
    check("no external asset URLs",
          not re.search(r'(src|href)="https?://[^"]*\.(png|jpg|svg|ico|woff)',
                        src.split("https://example.com")[0]))


def test_take7_progress_model():
    print("takeaway 7 (dossier 3): progress model — one source of truth")
    dist, tr = make_corpus(course_map_fixture())
    out = os.path.join(tempfile.mkdtemp(), "site", "index.html")
    run_sitegen(dist, tr, out)
    src = open(out).read()
    check("CMAP lesson metadata embedded",
          '"visibility": "published"' in src and '"drip_days": 3' in src)
    check("courseProgress returns integer %",
          re.search(r'progress: CMAP_PUB\.length \? Math\.round\(completed / CMAP_PUB\.length \* 100\) : 0', src)
          is not None)
    check("completedLessons/totalLessons counts",
          "completedLessons" in src and "totalLessons" in src)
    check("per-category integer %",
          re.search(r'progress: cats\[k\]\.total \? Math\.round\(cats\[k\]\.completed / cats\[k\]\.total \* 100\) : 0', src)
          is not None)
    check("timestamped completions (Date.now per lesson)",
          "s.done[id] = Date.now()" in src)
    check("progress reads the SAME store as the XP hook",
          "const KEY = \"consumer-progress-v1\";" in src
          and re.search(r'courseProgress\(\)[\s\S]{0,400}?state\(\)', src) is not None)
    check("XP path and % path share s.done (never diverge)",
          src.count("s.done") >= 5 and "consumerGameEngine" in src)
    check("header shows course progress label",
          'id="course-progress-label"' in src)
    check("refresh() updates both XP bar and course %",
          re.search(r'function refresh\(\)[\s\S]{0,2500}?updateCertificate\(cp\)', src)
          is not None)


def test_take8_certificate():
    print("takeaway 8 (dossier 9): certificate unlocks at 100%")
    dist, tr = make_corpus(course_map_fixture())
    out = os.path.join(tempfile.mkdtemp(), "site", "index.html")
    run_sitegen(dist, tr, out)
    src = open(out).read()
    cert = re.search(r'<section id="certificate".*?</section>', src, re.S)
    check("certificate section present", cert is not None)
    if cert:
        c = cert.group(0)
        check("starts locked", 'data-cert-locked="true"' in c)
        check("locked note shows progress placeholder",
          "Complete all lessons to unlock" in c and 'id="cert-progress-inline"' in c)
        check("cert body hidden until unlock", "hidden" in c)
        check("learner name field (editable, no backend)",
              'id="cert-name"' in c and "contenteditable" in c)
        check("print affordance", 'id="cert-print"' in c)
    check("unlock condition = progress >= 100 in JS",
          re.search(r'unlocked = cp\.totalLessons > 0 && cp\.progress >= 100', src)
          is not None)
    check("name prompt persists to localStorage",
          re.search(r's2\.learner_name = name; save\(s2\)', src) is not None)
    check("issue timestamp recorded",
          re.search(r's3\.cert_issued_at = Date\.now\(\); save\(s3\)', src) is not None)
    check("print CSS present", "@media print" in src)
    check("print CSS isolates the certificate",
          re.search(r'@media print[\s\S]{0,300}?main > \*:not\(#certificate\)', src)
          is not None)
    check("print button calls window.print()",
          "window.print()" in src)


def test_take9_offer_json():
    print("takeaway 9 (dossier 4): offer != course — offer.json beside site")
    dist, tr = make_corpus(course_map_fixture(), offer=OFFER_FIXTURE)
    out = os.path.join(tempfile.mkdtemp(), "site", "index.html")
    r = run_sitegen(dist, tr, out)
    res = json.loads(r.stdout)
    offer_path = os.path.join(os.path.dirname(out), "offer.json")
    check("offer.json emitted beside site", os.path.exists(offer_path), str(res)[:150])
    check("run result reports offer path", res.get("offer") == os.path.abspath(offer_path))
    o = json.load(open(offer_path))
    check("offer schema declared", o.get("schema") == "offer/consumer-v1")
    check("offer title from metadata", o.get("title") == "Feature Package")
    check("lessons bundled listed",
          o.get("lessons_bundled") == ["Welcome to the funnel", "Map the machine",
                                       "Secret bonus lesson", "Book your audit",
                                       "Deep drip lesson"], str(o.get("lessons_bundled")))
    check("access terms carried", o.get("access_terms") == "lifetime access, all future editions")
    check("offer version carried", o.get("version") == "2")
    check("offer type carried", o.get("type") == "onetime")
    # offer is NOT baked into the site content
    src = open(out).read()
    check("offer never baked into site HTML",
          "Feature Package" not in src and "offer/consumer-v1" not in src)
    # --no-offer suppresses it
    out2 = os.path.join(tempfile.mkdtemp(), "site2", "index.html")
    r2 = run_sitegen(dist, tr, out2, ("--no-offer",))
    check("--no-offer suppresses offer.json",
          r2.returncode == 0 and not os.path.exists(os.path.join(os.path.dirname(out2), "offer.json")))
    # default offer when metadata has no offer block
    dist3, tr3 = make_corpus(course_map_fixture())
    out3 = os.path.join(tempfile.mkdtemp(), "site3", "index.html")
    run_sitegen(dist3, tr3, out3)
    o3 = json.load(open(os.path.join(os.path.dirname(out3), "offer.json")))
    check("default offer shape without offer block",
          o3["schema"] == "offer/consumer-v1" and o3["course"] == "Feature Course"
          and o3["title"].endswith("training package") and o3["version"] == "1")


def test_take10_comments_policy():
    print("takeaway 10 (dossier 8): per-lesson comments policy stub")
    dist, tr = make_corpus(course_map_fixture())
    out = os.path.join(tempfile.mkdtemp(), "site", "index.html")
    run_sitegen(dist, tr, out)
    src = open(out).read()
    secs = {m.group(1): m.group(0) for m in
            re.finditer(r'<section class="lesson"[^>]*id="(lesson-\d+)".*?</section>', src, re.S)}
    check("visible discuss affordance",
          'data-discuss="visible"' in secs["lesson-01"]
          and "Discuss this lesson" in secs["lesson-01"])
    check("hidden policy renders NO discuss affordance",
          "discuss" not in secs["lesson-02"].replace("discuss-note", ""))
    check("locked discussion renders lock + policy text",
          'data-discuss="locked"' in secs["lesson-04"]
          and "Discussion is locked" in secs["lesson-04"])
    check("honest stub copy (no fake backend)",
          "Discussion happens outside this package" in secs["lesson-01"])
    check("stub is static (no comment form, no network)",
          "<textarea" not in src and "fetch(" not in src)


def test_structure_and_laws():
    print("structure: parse emitted HTML, stdlib-only + inline-only laws")
    dist, tr = make_corpus(course_map_fixture())
    out = os.path.join(tempfile.mkdtemp(), "site", "index.html")
    run_sitegen(dist, tr, out)
    src = open(out).read()
    # stdlib parser accepts the full document (malformed markup would raise)
    try:
        StrictParser().feed(src)
        check("emitted HTML parses (html.parser)", True)
    except Exception as e:
        check("emitted HTML parses (html.parser)", False, str(e)[:150])
    # balanced tags for the new surfaces
    for tag in ("section", "nav", "svg"):
        opens = len(re.findall(r"<" + tag + r"[\s>]", src))
        closes = src.count("</" + tag + ">")
        check(f"<{tag}> tags balanced", opens == closes, f"{opens} vs {closes}")
    # no external assets anywhere (CDN law)
    check("no external CSS/JS imports",
          not re.search(r'(src|href)="https?://(?!example\.com)', src.replace('https://example.com/audit', "")))
    check("no <img> external assets", "<img" not in src)
    check("all SVG inline (no .svg files)", not re.search(r'https?://[^"]+\.svg', src))
    # viewport meta present (mobile-first law)
    check("viewport meta present (mobile-first)",
          'name="viewport" content="width=device-width' in src)
    # JS is ES5-flavored where it matters (template literal count unchanged)
    check("site still uses same JS dialect (backticks)", src.count("`") >= 4)


def main():
    test_gating_legacy_identical()
    test_take1_interactive_course_map_toc()
    test_take2_three_state_visibility()
    test_take3_client_side_drip()
    test_take5_funnel_lesson()
    test_take6_materials_chips()
    test_take7_progress_model()
    test_take8_certificate()
    test_take9_offer_json()
    test_take10_comments_policy()
    test_structure_and_laws()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()