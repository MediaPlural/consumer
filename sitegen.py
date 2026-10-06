#!/usr/bin/env python3
"""consumer sitegen — build a self-contained course site from a distilled corpus.

Reads a distilled corpus dir (course-map.md, keywords.json, concepts.json,
next-best-seeds.json) + optional lesson transcripts (from distill.py's input
dir or --lessons), and emits ONE self-contained HTML file:

  - Toggleable floating ToC (collapsible, tracks scroll position)
  - "Insights" per lesson (Foxy-style: 3-5 bullet synthesis + keywords-in-play)
  - Progression: per-lesson completion tracking, XP per lesson, level curve
    (hooks named xp/level are wired for the MediaPlural game engine adapter;
    external users get a clean localStorage implementation)
  - Editions: lessons are fully editable in-page (contenteditable), and the
    site exports the edited corpus as a new edition (JSON download) — the
    "customize and edit all lessons into a new version" surface
  - Training mode: emits training-package/ (manifest + per-lesson content)
    for internal/external training use
  - Guild adapter: OPTIONAL --game-adapter flag emits game-adapter.js next
    to the site — it wraps window.consumerGameEngine and forwards lesson
    completions / XP gains to the Viiy Guild progression schema
    (guild-progression-v1). Contract: docs/GAME-ADAPTER.md. Stdlib-only,
    no network, no keys.

Usage:
  python3 sitegen.py ./my-course/distilled [--lessons ./my-course/transcripts] \\
      --title "Course Title" --out ./my-course/site/index.html \\
      [--game-adapter]
"""
import argparse
import hashlib
import html as html_mod
import json
import os
import re
import sys
import time


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        return json.load(open(path))
    except Exception:
        return default


def load_lessons(lessons_dir):
    """Transcript files -> ordered lesson list [{id, title, text, dur_s, seg_count}]."""
    lessons = []
    if not lessons_dir or not os.path.isdir(lessons_dir):
        return lessons
    files = sorted(f for f in os.listdir(lessons_dir) if f.endswith(".transcript.json"))
    for i, fname in enumerate(files, 1):
        try:
            d = json.load(open(os.path.join(lessons_dir, fname), errors="replace"))
        except Exception:
            continue
        text = d.get("text", "").strip()
        segs = d.get("segments", [])
        title = text.split(".")[0][:70] or f"Lesson {i}"
        lessons.append({"id": f"lesson-{i:02d}",
                        "file": fname,
                        "title": title,
                        "text": text,
                        "dur_s": round(segs[-1]["end"], 1) if segs else None,
                        "segments": len(segs)})
    return lessons


def summarize_local(text, keywords, concepts, seeds, n_bullets=5):
    """Foxy-style Insights: extractive synthesis with keyword/concept anchoring.
    Stdlib-only: sentence scoring by keyword density + position, top-N bullets.
    (The LLM layer can replace this whole function downstream — see HANDBOOK.)
    """
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 25]
    if not sents:
        return ["(lesson had no extractable sentences)"]
    kw = {k["term"] for k in keywords[:60]}
    scored = []
    for idx, s in enumerate(sents):
        words = re.findall(r"[a-z']+", s.lower())
        if not words:
            continue
        density = sum(1 for w in words if w in kw) / len(words)
        # position bonus: early sentences carry the lesson's thesis
        pos_bonus = 1.0 if idx < 3 else 0.0
        scored.append((density + pos_bonus, idx, s))
    scored.sort(key=lambda x: (-x[0], x[1]))
    bullets = []
    seen_terms = set()
    for _, idx, s in scored:
        low = s.lower()
        # dedupe near-identical sentences across bullets
        sig = " ".join(sorted(set(re.findall(r"[a-z]{4,}", low)))[:8])
        if sig in seen_terms:
            continue
        seen_terms.add(sig)
        bullets.append({"order": idx, "text": s})
        if len(bullets) >= n_bullets:
            break
    bullets.sort(key=lambda b: b["order"])
    return [b["text"] for b in bullets]


def insights_for_lesson(lesson, keywords, concepts, seeds):
    return {
        "summary": summarize_local(lesson["text"], keywords, concepts, seeds),
        "keywords_in_play": [k["term"] for k in keywords
                             if k["term"] in lesson["text"].lower()][:12],
        "concepts_in_play": [c["phrase"] for c in concepts
                             if c["phrase"].lower() in lesson["text"].lower()][:6],
        "seed": next((s["sentence"] for s in seeds
                      if s["sentence"][:40] not in lesson["text"][:200]), None),
    }


def xp_for_lesson(lesson, idx):
    """XP curve: base 40 + duration bonus + early-lesson ramp. Total course XP
    feeds the game-engine adapter (HANDBOOK §XP) — same numbers, both surfaces."""
    base = 40
    dur = lesson.get("dur_s") or 0
    dur_bonus = min(int(dur // 30), 40)
    ramp = max(0, 6 - idx) * 2  # first lessons slightly heavier (onboarding)
    return base + dur_bonus + ramp


# --- Guild progression adapter (contract: docs/GAME-ADAPTER.md) -------------
#
# Canonical guild event schema, read from the viiy-hq guild progression
# codex (READ-ONLY sources, cited in docs/GAME-ADAPTER.md):
#   - viiy-hq/game/design/XP-REWARD-SYSTEM.md  (quest tiers, XP sources,
#     reward-event resolution sequence, quality multipliers)
#   - viiy-hq/game/design/PROGRESSION-STATS-CODEX-v2.md (stage/rank ladder:
#     18 stages, 4 bands Early/Middle/Late/Peak, Level 1-100 per stage,
#     Twin Realm: worldly_rank vs soul_stage)
#   - viiy-hq/guild/identity-tags/backend/SIGNING.md + ENROLLMENT-FLOW.md
#     (member identity: member_uuid, rank, rank_level)
#
# A consumer lesson completion maps onto a guild Quest Completion XP event
# (XP-REWARD-SYSTEM §1.2.1 — "verified real-world striving"; tier "Trivial"
# to "Minor" band by lesson XP size). Event envelope fields (canonical names):
GUILD_EVENT_VERSION = "guild-progression-v1"
GUILD_EVENT_KIND_XP = "xp_gain"
GUILD_EVENT_KIND_LESSON = "lesson_complete"
GUILD_EVENT_KIND_LEVEL = "level_up"
# payload field names (canonical guild side):
#   member_uuid, source, quest_id, quest_tier, quality, xp_delta,
#   xp_total, level, rank, rank_level, band, occurred_at

QUEST_TIERS = [  # (min xp, tier name) — XP-REWARD-SYSTEM §1.2.1 quest tier table
    (0, "Trivial"),      # 5-15 XP band, daily tasks
    (25, "Minor"),       # 25-75 XP, single-session deliverables
    (100, "Standard"),   # 100-300 XP, regular project work
    (500, "Major"),       # 500-1500 XP, multi-week initiatives
    (3000, "Legendary"),  # 3000-10000 XP, realm-crossing milestones
    (25000, "Mythic"),    # 25000+ XP, once-per-lifetime
]


def quest_tier_for(xp_delta):
    """Consumer lesson XP -> canonical guild quest tier (XP-REWARD-SYSTEM §1.2.1)."""
    tier = QUEST_TIERS[0][1]
    for floor, name in QUEST_TIERS:
        if xp_delta >= floor:
            tier = name
    return tier


def quality_for(xp_delta):
    """Consumer completions are self-marked, not adjudicated -> quality is
    'Standard' (x1.0). The guild's VERIFY step (§6.1) upgrades it later."""
    return "Standard"


def guild_event(kind, payload):
    """Build one canonical guild progression event (schema guild-progression-v1)."""
    return {"schema": GUILD_EVENT_VERSION, "kind": kind, "payload": payload}


def adapter_script(title, xp_total):
    """game-adapter.js — wraps window.consumerGameEngine and forwards consumer
    XP events to the guild progression schema. Pure client-side mapping; the
    transport (window.guildBridge) is provided by the guild loader at deploy
    time (docs/GAME-ADAPTER.md §3). Stdlib-generated, zero dependencies."""
    return f"""// game-adapter.js — consumer -> Viiy Guild progression adapter
// Schema: {GUILD_EVENT_VERSION} (contract: docs/GAME-ADAPTER.md)
// Generated by sitegen.py --game-adapter for "{title}"
// Source hook: window.consumerGameEngine({{xp, level, done}}) per refresh().
(function () {{
  var SCHEMA = {json.dumps(GUILD_EVENT_VERSION)};
  var COURSE = {json.dumps(title)};
  var XP_TOTAL = {xp_total};
  var TIERS = {json.dumps(QUEST_TIERS)};
  var last = {{xp: null, level: null, done: {{}}}};
  var bridge = function () {{ return (window.guildBridge && typeof window.guildBridge.emit === "function") ? window.guildBridge : null; }};

  function tierFor(xpDelta) {{
    var t = TIERS[0][1];
    for (var i = 0; i < TIERS.length; i++) if (xpDelta >= TIERS[i][0]) t = TIERS[i][1];
    return t;
  }}
  function emit(kind, payload) {{
    var b = bridge();
    var ev = {{schema: SCHEMA, kind: kind, payload: payload}};
    if (b) {{
      try {{ b.emit(ev); }} catch (e) {{ /* guild loader owns retry */ }}
    }} else {{
      // no bridge yet: queue for the guild loader's polling fallback
      // (never both — the flush below would double-deliver)
      try {{
        var q = JSON.parse(localStorage.getItem("guild-adapter-queue") || "[]");
        q.push(ev); localStorage.setItem("guild-adapter-queue", JSON.stringify(q.slice(-200)));
      }} catch (e) {{}}
    }}
    return ev;
  }}
  function iso(ts) {{ return new Date(ts).toISOString(); }}

  // canonical field names: member_uuid, source, quest_id, quest_tier, quality,
  // xp_delta, xp_total, level, rank, rank_level, band, occurred_at
  function memberUuid() {{
    try {{ return localStorage.getItem("guild-member-uuid") || null; }}
    catch (e) {{ return null; }}
  }}

  window.consumerGameEngine = function (snap) {{
    // snap = {{xp, level, done}} from the site's refresh(); NB the site passes
    // `done` as a COUNT (Object.keys(s.done).length), so the authoritative
    // per-lesson map is read from the site's own localStorage state.
    var doneMap = {{}};
    try {{
      var st = JSON.parse(localStorage.getItem("consumer-progress-v1") || "{{}}");
      doneMap = st.done || {{}};
    }} catch (e) {{}}
    var mu = memberUuid();
    var newlyDone = Object.keys(doneMap).filter(function (id) {{
      return doneMap[id] && !last.done[id];
    }});
    var xpDelta = last.xp === null ? 0 : snap.xp - last.xp;

    // 1. lesson_complete event per newly completed lesson (quest completion)
    newlyDone.forEach(function (id) {{
      var el = document.querySelector('.lesson[data-lesson="' + id + '"]');
      var lessonXp = el ? parseInt(el.dataset.xp || 0, 10) : 0;
      emit({json.dumps(GUILD_EVENT_KIND_LESSON)}, {{
        member_uuid: mu,
        source: "consumer",
        course: COURSE,
        quest_id: id,
        quest_tier: tierFor(lessonXp),
        quality: "Standard",
        xp_delta: lessonXp,
        xp_total: snap.xp,
        level: snap.level,
        rank: null, rank_level: null, band: null,
        occurred_at: iso(doneMap[id])
      }});
    }});

    // 2. xp_gain event when total XP moved
    if (last.xp !== null && xpDelta !== 0) {{
      emit({json.dumps(GUILD_EVENT_KIND_XP)}, {{
        member_uuid: mu,
        source: "consumer",
        quest_id: newlyDone.length ? newlyDone[newlyDone.length - 1] : null,
        quest_tier: tierFor(Math.abs(xpDelta)),
        quality: "Standard",
        xp_delta: xpDelta,
        xp_total: snap.xp,
        level: snap.level,
        rank: null, rank_level: null, band: null,
        occurred_at: new Date().toISOString()
      }});
    }}

    // 3. level_up event on level crossings (guild Level 1-100 within a stage,
    //    band Early/Middle/Late/Peek -> mapped per Codex v2 §1.4)
    if (last.level !== null && snap.level > last.level) {{
      emit({json.dumps(GUILD_EVENT_KIND_LEVEL)}, {{
        member_uuid: mu,
        source: "consumer",
        quest_id: null,
        quest_tier: null,
        quality: null,
        xp_delta: null,
        xp_total: snap.xp,
        level: snap.level,
        rank: null, rank_level: null,
        band: (snap.level >= 76) ? "Peak" : (snap.level >= 51) ? "Late" : (snap.level >= 26) ? "Middle" : "Early",
        occurred_at: new Date().toISOString()
      }});
    }}

    last = {{xp: snap.xp, level: snap.level, done: Object.assign({{}}, doneMap)}};
    // flush the queue to the guild bridge when present (loader drains it)
    var b = bridge();
    if (b) {{
      try {{
        var q = JSON.parse(localStorage.getItem("guild-adapter-queue") || "[]");
        q.forEach(function (ev) {{ b.emit(ev); }});
        localStorage.setItem("guild-adapter-queue", "[]");
      }} catch (e) {{}}
    }}
  }};
}})();
"""


def build_site(title, course_map_md, keywords, concepts, seeds, lessons, brand):
    esc = html_mod.escape
    kw_json = json.dumps(keywords[:80])
    seeds_json = json.dumps(seeds[:40])
    concepts_json = json.dumps(concepts[:60])

    toc_items = []
    lesson_html = []
    insights_html = []
    xp_total = sum(xp_for_lesson(l, i) for i, l in enumerate(lessons))
    for i, lesson in enumerate(lessons, 1):
        lid = lesson["id"]
        ins = insights_for_lesson(lesson, keywords, concepts, seeds)
        xp = xp_for_lesson(lesson, i - 1)
        toc_items.append(
            f'<li><a href="#{lid}" data-lesson="{lid}">{i}. {esc(lesson["title"])}</a></li>')
        dur = f"{round(lesson['dur_s']/60,1)} min" if lesson.get("dur_s") else "—"
        bullets = "\n".join(f"<li>{esc(b)}</li>" for b in ins["summary"])
        kws = " ".join(f'<span class="kw">{esc(k)}</span>' for k in ins["keywords_in_play"])
        cons = " ".join(f'<span class="cpt">{esc(c)}</span>' for c in ins["concepts_in_play"])
        seed_html = ""
        if ins["seed"]:
            seed_html = f'<div class="seed">Next-best: <em>{esc(ins["seed"])}</em></div>'
        lesson_html.append(f"""
<section class="lesson" id="{lid}" data-lesson="{lid}" data-xp="{xp}">
  <div class="lesson-head">
    <h2>{i}. {esc(lesson["title"])}</h2>
    <span class="meta">{dur} · {lesson["segments"]} segments · +{xp} XP</span>
    <button class="complete-btn" data-lesson="{lid}">Mark complete</button>
  </div>
  <div class="insights">
    <h3>Insights</h3>
    <ul class="insight-list">{bullets}</ul>
    {seed_html}
    <div class="tags">{kws} {cons}</div>
  </div>
  <details class="full-text"><summary>Full transcript</summary>
    <div class="lesson-body" contenteditable="true">{esc(lesson["text"])}</div>
  </details>
</section>""")
        insights_html.append(bullets)

    toc = "\n".join(toc_items)
    lessons_js = json.dumps([{"id": l["id"], "title": l["title"], "text": l["text"],
                             "dur_s": l.get("dur_s"), "segments": l["segments"],
                             "file": l["file"]} for l in lessons])
    insight_js = json.dumps(
        {l["id"]: insights_for_lesson(l, keywords, concepts, seeds) for l in lessons})

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
:root {{
  --bg: {brand['bg']}; --panel: {brand['panel']}; --ink: {brand['ink']};
  --accent: {brand['accent']}; --muted: {brand['muted']}; --xp: {brand['xp']};
}}
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
       background: var(--bg); color: var(--ink); line-height: 1.55; }}
header {{ position: sticky; top: 0; z-index: 50; background: var(--panel);
          border-bottom: 1px solid rgba(128,128,128,.25); padding: .6rem 1rem;
          display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }}
header h1 {{ font-size: 1.05rem; margin: 0; flex: 1; min-width: 200px; }}
#xp-bar {{ display: flex; gap: 1rem; align-items: center; font-size: .85rem; }}
#xp-fill {{ width: 160px; height: 10px; background: rgba(128,128,128,.25);
            border-radius: 6px; overflow: hidden; }}
#xp-fill i {{ display: block; height: 100%; width: 0%;
              background: var(--xp); transition: width .4s; }}
#toc-toggle {{ position: fixed; bottom: 18px; left: 18px; z-index: 90;
  border: none; border-radius: 999px; padding: .55rem 1rem; cursor: pointer;
  background: var(--accent); color: #fff; font-weight: 600; box-shadow: 0 4px 18px rgba(0,0,0,.35); }}
#toc {{ position: fixed; bottom: 70px; left: 18px; z-index: 89; width: 300px;
  max-height: 60vh; overflow: auto; background: var(--panel);
  border: 1px solid rgba(128,128,128,.3); border-radius: 12px; padding: .8rem;
  display: none; }}
#toc.open {{ display: block; }}
#toc a {{ display: block; padding: .25rem .4rem; color: var(--ink);
          text-decoration: none; border-radius: 6px; font-size: .85rem; }}
#toc a.done {{ color: var(--muted); }}
#toc a.done::before {{ content: "✓ "; color: var(--xp); }}
main {{ max-width: 860px; margin: 0 auto; padding: 1rem 1rem 6rem; }}
.lesson {{ background: var(--panel); border-radius: 14px; padding: 1.2rem 1.4rem;
           margin: 1.2rem 0; border: 1px solid rgba(128,128,128,.18); }}
.lesson.done {{ outline: 2px solid var(--xp); }}
.lesson-head {{ display: flex; gap: .8rem; align-items: baseline; flex-wrap: wrap; }}
.lesson-head h2 {{ font-size: 1.05rem; margin: 0; flex: 1; }}
.meta {{ color: var(--muted); font-size: .8rem; }}
.complete-btn {{ background: var(--accent); border: none; color: #fff; padding: .35rem .8rem;
                  border-radius: 8px; cursor: pointer; font-size: .8rem; }}
.complete-btn.done {{ background: var(--xp); }}
.insights {{ background: rgba(128,128,128,.08); border-radius: 10px; padding: .8rem 1rem; margin-top: .8rem; }}
.insights h3 {{ margin: 0 0 .4rem; font-size: .8rem; text-transform: uppercase;
               letter-spacing: .06em; color: var(--muted); }}
.insight-list {{ margin: 0; padding-left: 1.1rem; }}
.insight-list li {{ margin: .25rem 0; font-size: .95rem; }}
.seed {{ margin-top: .5rem; font-size: .85rem; color: var(--muted); }}
.tags {{ margin-top: .5rem; }}
.kw, .cpt {{ display: inline-block; font-size: .7rem; padding: .1rem .5rem;
            border-radius: 999px; margin: .15rem .15rem 0 0; }}
.kw {{ background: color-mix(in srgb, var(--accent) 25%, transparent); }}
.cpt {{ background: color-mix(in srgb, var(--xp) 25%, transparent); }}
details.full-text {{ margin-top: .8rem; }}
details.full-text summary {{ cursor: pointer; color: var(--muted); font-size: .85rem; }}
.lesson-body {{ margin-top: .6rem; white-space: pre-wrap; font-size: .95rem;
                border-radius: 8px; padding: .6rem; }}
.lesson-body:focus {{ outline: 2px solid var(--accent); }}
#export-btn, #train-btn {{ background: transparent; border: 1px solid var(--accent);
  color: var(--accent); padding: .35rem .8rem; border-radius: 8px; cursor: pointer; font-size: .8rem; }}
#toast {{ position: fixed; bottom: 80px; right: 18px; background: var(--panel);
  border: 1px solid var(--xp); color: var(--ink); padding: .6rem 1rem; border-radius: 10px;
  display: none; z-index: 95; }}
</style>
</head>
<body>
<header>
  <h1>{esc(title)}</h1>
  <div id="xp-bar">
    <span id="xp-label">0 / {xp_total} XP</span>
    <div id="xp-fill"><i id="xp-prog"></i></div>
    <span id="level-label">Level 1</span>
  </div>
  <button id="export-btn" title="Export your edited lessons as a new edition">Export edition</button>
  <button id="train-btn" title="Package this course as a training package">Training package</button>
</header>
<button id="toc-toggle">☰ Contents</button>
<nav id="toc"><ul style="list-style:none;padding:0;margin:0">{toc}</ul></nav>
<main>
<section id="course-map" style="white-space:pre-wrap">{esc(course_map_md)}</section>
{"".join(lesson_html)}
</main>
<div id="toast"></div>
<script>
const LESSONS = {lessons_js};
const INSIGHTS = {insight_js};
const KW = {kw_json};
const KEY = "consumer-progress-v1";

function state() {{
  try {{ return JSON.parse(localStorage.getItem(KEY)) || {{done: {{}}, edits: {{}}, xp: 0}}; }}
  catch(e) {{ return {{done: {{}}, edits: {{}}, xp: 0}}; }}
}}
function save(s) {{ localStorage.setItem(KEY, JSON.stringify(s)); }}
function toast(msg) {{
  const t = document.getElementById("toast");
  t.textContent = msg; t.style.display = "block";
  setTimeout(() => t.style.display = "none", 2200);
}}
function levelFor(xp) {{ return Math.max(1, Math.floor(xp / 120) + 1); }}

function refresh() {{
  const s = state();
  const done = Object.keys(s.done).length;
  const xp = Object.keys(s.done).reduce((acc, id) => {{
    // scope to the lesson section: the ToC link carries data-lesson too,
    // precedes main in document order, and has no data-xp (the live browser
    // test caught this: XP showed 0 with the lesson visibly completed)
    const el = document.querySelector(`.lesson[data-lesson="${{id}}"]`);
    return acc + (el ? parseInt(el.dataset.xp || 0, 10) : 0);
  }}, 0);
  document.getElementById("xp-label").textContent = xp + " / {xp_total} XP";
  document.getElementById("xp-prog").style.width = Math.min(100, xp / {xp_total or 1} * 100) + "%";
  document.getElementById("level-label").textContent = "Level " + levelFor(xp);
  document.querySelectorAll(".lesson").forEach(el => {{
    const id = el.dataset.lesson;
    el.classList.toggle("done", !!s.done[id]);
    const btn = el.querySelector(".complete-btn");
    btn.classList.toggle("done", !!s.done[id]);
    btn.textContent = s.done[id] ? "✓ Completed" : "Mark complete";
    document.querySelectorAll(`#toc a[data-lesson="${{id}}"]`).forEach(a => a.classList.toggle("done", !!s.done[id]));
  }});
  if (window.consumerGameEngine) window.consumerGameEngine({{xp, level: levelFor(xp), done}});
}}

document.getElementById("toc-toggle").addEventListener("click", () => {{
  document.getElementById("toc").classList.toggle("open");
}});
document.querySelectorAll(".complete-btn").forEach(btn => {{
  btn.addEventListener("click", () => {{
    const s = state();
    const id = btn.dataset.lesson;
    if (s.done[id]) {{ delete s.done[id]; }} else {{ s.done[id] = Date.now(); }}
    save(s); refresh();
    toast(s.done[id] ? "+" + (document.querySelector(`.lesson[data-lesson="${{id}}"]`).dataset.xp) + " XP" : "Progress reverted");
  }});
}});

// capture in-page lesson edits (contenteditable) into the edition export
document.querySelectorAll(".lesson-body").forEach(body => {{
  body.addEventListener("input", () => {{
    const s = state();
    const id = body.closest(".lesson").dataset.lesson;
    s.edits[id] = body.innerText;
    save(s);
  }});
}});

document.getElementById("export-btn").addEventListener("click", () => {{
  const s = state();
  const edition = {{
    title: {json.dumps(title)},
    exported_at: new Date().toISOString(),
    base_lessons: LESSONS,
    edits: s.edits,
    progress: {{done: s.done, xp_total: {xp_total}}},
  }};
  const blob = new Blob([JSON.stringify(edition, null, 2)], {{type: "application/json"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "edition-" + Date.now() + ".json";
  a.click();
  toast("Edition exported");
}});

document.getElementById("train-btn").addEventListener("click", () => {{
  const s = state();
  const pkg = {{
    title: {json.dumps(title)},
    generated_at: new Date().toISOString(),
    mode: "training",
    lessons: LESSONS.map(l => ({{
      id: l.id, title: l.title,
      content: s.edits[l.id] || l.text,
      insights: INSIGHTS[l.id],
    }})),
    rubric: {{
      per_lesson: ["Learner can state the lesson's core claim",
                   "Learner can name the keywords-in-play",
                   "Learner can apply the next-best-sentence to their own context"],
    }},
  }};
  const blob = new Blob([JSON.stringify(pkg, null, 2)], {{type: "application/json"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "training-package-" + Date.now() + ".json";
  a.click();
  toast("Training package exported");
}});

refresh();
</script>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser(description="Distilled corpus -> self-contained course site")
    ap.add_argument("distilled_dir")
    ap.add_argument("--lessons", default=None, help="transcripts dir (adds lesson sections)")
    ap.add_argument("--title", default="Course")
    ap.add_argument("--out", default=None)
    ap.add_argument("--brand", choices=["dark", "light"], default="dark")
    ap.add_argument("--game-adapter", action="store_true",
                    help="emit game-adapter.js (guild progression bridge, docs/GAME-ADAPTER.md)")
    a = ap.parse_args()

    d = a.distilled_dir
    cmap_path = os.path.join(d, "course-map.md")
    course_map = open(cmap_path, errors="replace").read() if os.path.exists(cmap_path) else "(no course-map.md)"
    keywords = load_json(os.path.join(d, "keywords.json"), {"keywords": []})["keywords"]
    concepts = load_json(os.path.join(d, "concepts.json"), {"concepts": []})["concepts"]
    seeds = load_json(os.path.join(d, "next-best-seeds.json"), {"seeds": []})["seeds"]
    lessons = load_lessons(a.lessons) or load_lessons(os.path.join(d, "..", "transcripts"))
    if not lessons:
        print("note: no lesson transcripts found — site will carry the course map only", file=sys.stderr)

    brand = ("dark" if a.brand == "dark" else "light") == "dark" and {
        "bg": "#0e0f13", "panel": "#16181f", "ink": "#e8eaf0", "accent": "#7c5cff",
        "muted": "#8b90a0", "xp": "#38d39f"} or {
        "bg": "#f7f8fa", "panel": "#ffffff", "ink": "#17181d", "accent": "#5b45d6",
        "muted": "#6b7280", "xp": "#0e9f6e"}

    site = build_site(a.title, course_map, keywords, concepts, seeds, lessons, brand)
    out = a.out or os.path.join(d, "site", "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(site)
    result = {"ok": True, "out": os.path.abspath(out), "lessons": len(lessons),
              "bytes": len(site)}
    if a.game_adapter:
        xp_total = sum(xp_for_lesson(l, i) for i, l in enumerate(lessons))
        adapter_path = os.path.join(os.path.dirname(out), "game-adapter.js")
        with open(adapter_path, "w") as f:
            f.write(adapter_script(a.title, xp_total))
        result["game_adapter"] = os.path.abspath(adapter_path)
        result["guild_schema"] = GUILD_EVENT_VERSION
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()