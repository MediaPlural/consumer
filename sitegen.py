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
  - Course-map metadata (OPTIONAL course-map.json, consumer-v1 flat shape or
    the HighLevel ingest shape course-map/highlevel-v1 — auto-detected in or
    beside the distilled dir, or via --course-map-json; see the HL membership
    UX dossier §5 takeaways). Gates, with zero impact on corpora without it:
      * interactive course-map TOC: per-lesson checkboxes persisted in the
        same consumer-progress-v1 localStorage, per-category % progress
      * three-state lesson visibility: draft (hidden from nav, unlinked),
        published (default), locked (lock glyph + unlock-condition text)
      * client-side drip: drip_days per lesson, enrollment date = first
        visit; locked+future lessons render "unlocks in X days"
      * funnel lessons: contentType 'funnel' renders an action-card CTA
      * materials[] chips with inline-SVG type icons (no external assets)
      * per-lesson comments policy: visible/hidden/locked 'discuss' stub
      * printable certificate page, unlocked at 100% completion
      * offer.json beside the site (offer != course: access packaging is
        metadata, never baked into content)

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


# --- course-map metadata (HL membership UX dossier §5, takeaways 1-3,5-9) ---

CMAP_SCHEMA = "course-map/consumer-v1"

#: valid lesson visibility states (HL: draft/published/locked)
VISIBILITY_STATES = ("draft", "published", "locked")
#: valid per-lesson comment-policy states (HL: visible/hidden/locked)
COMMENT_STATES = ("visible", "hidden", "locked")


def norm_course_map(raw, title, lessons):
    """course-map.json -> normalized metadata, or None when absent.

    Accepts both shapes:
      - consumer-v1: {"schema": "course-map/consumer-v1", "categories": ...}
      - HighLevel ingest (hl_course.py): {"schema": "course-map/highlevel-v1",
            "product": {...}, "categories": [{"id","title","visibility",
            "lessons": [{id, title, visibility, contentType, commentStatus,
                        commentPermission, drip...}]}]}

    Matching to transcript lessons is BY TITLE (the only join key present in
    both shapes); transcript order wins (site order contract), unmatched
    metadata entries are ignored, lessons without metadata stay default.
    Returns a dict {"categories", "lesson_meta", "offer"}; None when `raw`
    carries no metadata at all (legacy corpora -> legacy output, byte-identical).
    """
    if not isinstance(raw, dict):
        return None
    schema = raw.get("schema") or ""
    if not (schema.startswith("course-map/highlevel")
            or schema.startswith("course-map/consumer")):
        return None
    categories = raw.get("categories") or []

    lesson_meta = {}
    for c in categories:
        if not isinstance(c, dict):
            continue
        ctitle = (c.get("title") or "").strip()
        ckey = ctitle.casefold()
        for les in (c.get("lessons") or []):
            if not isinstance(les, dict):
                continue
            key = _mkey(les.get("title"))
            if not key:
                continue
            m = {"visibility": _pick(les.get("visibility"),
                                     VISIBILITY_STATES, "published"),
                 "content_type": les.get("contentType") or les.get("content_type"),
                 "category": ckey or None,
                 "category_title": ctitle,
                 "drip_days": _int_or_none(_first(les.get("drip_days"),
                                                 les.get("drip"))),
                 "unlock_condition": les.get("unlock_condition")
                 or les.get("unlockCondition") or les.get("description")
                 or None,
                 "comment_status": _pick(_first(les.get("comment_status"),
                                               les.get("commentStatus")),
                                         COMMENT_STATES, "visible"),
                 "materials": _norm_materials(les.get("materials")),
                 "funnel": _norm_funnel(_first(les.get("funnel"),
                                              les.get("action")))}
            if m["funnel"] is None and m["content_type"] == "funnel":
                m["funnel"] = {"url": "#", "label": "Take action"}
            lesson_meta[key] = m

    if not lesson_meta:
        return None  # empty map == legacy corpus, no metadata surface
    offer = _norm_offer(raw.get("offer"), title, lessons)
    return {"schema": CMAP_SCHEMA, "categories": categories,
            "categories_n": len(categories),
            "lesson_meta": lesson_meta, "offer": offer}


def _mkey(title):
    return " ".join(((title or "").strip().casefold()).split())


def _pick(val, allowed, default):
    return val if val in allowed else default


def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def _int_or_none(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _norm_materials(items):
    out = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        t = (it.get("title") or "").strip()
        if not t:
            continue
        out.append({"title": t,
                    "type": ((it.get("type") or "link").strip().lower()
                             or "link"),
                    "url": (it.get("url") or "#").strip() or "#"})
    return out


def _norm_funnel(f):
    if not isinstance(f, dict):
        return None
    url = (f.get("url") or "#").strip() or "#"
    label = (f.get("label") or "Take action").strip() or "Take action"
    return {"url": url, "label": label}


def _norm_offer(raw, title, lessons):
    """Offer != course (dossier §5.4): access packaging is separate metadata
    layered over the tree, never baked into it. Only explicit fields pass
    through; nothing is invented here."""
    o = {"schema": "offer/consumer-v1",
         "course": title,
         "lessons_bundled": [l["title"] for l in lessons],
         "version": "1"}
    if isinstance(raw, dict):
        o["title"] = raw.get("title") or f"{title} — training package"
        if raw.get("version") is not None:
            o["version"] = str(raw["version"])
        for src, dst in (("access_terms", "access_terms"),
                         ("accessTerms", "access_terms"),
                         ("terms", "access_terms"),
                         ("description", "description"),
                         ("type", "type"), ("amount", "amount"),
                         ("currency", "currency"), ("interval", "interval"),
                         ("interval_count", "interval_count"),
                         ("intervalCount", "interval_count"),
                         ("trial_days", "trial_days"), ("trialDays", "trial_days"),
                         ("days_of_access", "days_of_access"),
                         ("daysOfAccess", "days_of_access"),
                         ("access_date", "access_date"), ("accessDate", "access_date"),
                         ("visibility", "visibility")):
            v = raw.get(src)
            if v is not None:
                o[dst] = v
    else:
        o["title"] = f"{title} — training package"
    return o


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


# --- course-map site features (HL membership UX dossier §5, takeaways 1-3,5-9)

#: inline padlock glyph — pure inline SVG, no external assets (site law)
LOCK_SVG = ('<svg class="lock-glyph" viewBox="0 0 16 16" width="13" height="13" '
            'aria-hidden="true"><path d="M4 7V5a4 4 0 0 1 8 0v2h1v7H3V7h1zm2 0h4V5'
            'a2 2 0 0 0-4 0v2z" fill="currentColor"/></svg>')

#: minimal inline-SVG file-type icons for materials chips (dossier §5.7)
_MAT_ICON_PATHS = {
    "doc": '<path d="M3 1h7l3 3v11H3V1zm7 1.5V5h2.5L10 2.5zM5 7h6v1H5V7zm0 2.5h6v1H5v-1zm0 2.5h4v1H5v-1z" fill="currentColor"/>',
    "pdf": '<path d="M3 1h7l3 3v11H3V1zm7 1.5V5h2.5L10 2.5zM5 7h2.3a1.7 1.7 0 0 1 0 3.4H6.2v1.8H5V7zm1.2 1v1.4h1.1a.7.7 0 0 0 0-1.4H6.2z" fill="currentColor"/>',
    "video": '<path d="M2 2h12a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zm4 2.8v6.4L12 8 6 4.8z" fill="currentColor"/>',
    "audio": '<path d="M8 1a1 1 0 0 1 1 1v7.3a3 3 0 1 1-2 0V2a1 1 0 0 1 1-1z" fill="currentColor"/>',
    "zip": '<path d="M2 1h12v14H2V1zm6 1-1 2h2l-1 2h2L8 9l1-2H7l1-2H6l2-2V2zM4 11h8v2H4v-2z" fill="currentColor"/>',
    "image": '<path d="M2 3h12v10H2V3zm1 1v6.5l3-3 2 2 3-3L14 9V4H3zm2.2 1a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4z" fill="currentColor"/>',
    "link": '<path d="M9.5 6.5l-3 3 3-3zm-5 5a2.7 2.7 0 0 1 0-3.8l2-2-1.2-1.2-2 2a4.4 4.4 0 0 0 6.2 6.2l2-2-1.2-1.2-2 2a2.7 2.7 0 0 1-3.8 0zm7-10.2a4.4 4.4 0 0 0-6.2 0l-2 2 1.2 1.2 2-2a2.7 2.7 0 0 1 3.8 3.8l-2 2 1.2 1.2 2-2a4.4 4.4 0 0 0 0-6.2z" fill="currentColor"/>',
    "file": '<path d="M3 1h7l3 3v11H3V1zm7 1.5V5h2.5L10 2.5z" fill="currentColor"/>',
}
_MAT_ICON_KIND = {
    "pdf": "pdf", "doc": "doc", "docx": "doc", "rtf": "doc", "md": "doc", "txt": "doc",
    "video": "video", "mp4": "video", "mov": "video", "webm": "video", "avi": "video",
    "audio": "audio", "mp3": "audio", "wav": "audio", "m4a": "audio", "aac": "audio",
    "zip": "zip", "gz": "zip", "tar": "zip", "rar": "zip", "7z": "zip",
    "image": "image", "png": "image", "jpg": "image", "jpeg": "image", "gif": "image",
    "webp": "image", "svg": "image",
    "link": "link", "url": "link", "html": "link",
}


def material_icon(mtype):
    """Inline-SVG icon for a materials chip type (stdlib-only, no assets)."""
    kind = _MAT_ICON_KIND.get((mtype or "").lower(), "file")
    return ('<svg class="chip-icon" viewBox="0 0 16 16" width="14" height="14" '
            'aria-hidden="true">' + _MAT_ICON_PATHS[kind] + "</svg>")


def meta_toc_item(i, lesson, m, esc):
    """Floating-ToC row for a metadata site (draft lessons never reach here)."""
    m = m or {}
    lid = lesson["id"]
    lock = ""
    if m.get("visibility") == "locked" or m.get("drip_days") is not None:
        lock = '<span class="toc-lock" aria-label="locked">' + LOCK_SVG + "</span>"
    return (f'<li><a href="#{lid}" data-lesson="{lid}">{i}. {esc(lesson["title"])}'
            + lock + "</a></li>")


def render_meta_lesson(i, lesson, m, ins, xp, dur, bullets, kws, cons, seed_html, esc):
    """Lesson section for a metadata site: visibility states, drip, funnel
    action card, materials chips, discuss policy — same skeleton as the
    legacy lesson so visual weight is identical."""
    m = m or {}
    lid = lesson["id"]
    vis = m.get("visibility", "published")
    drip = m.get("drip_days")
    ctype = m.get("content_type")
    locked = vis == "locked"
    gated = locked or drip is not None

    attrs = f'data-visibility="{vis}"'
    if ctype:
        attrs += f' data-content-type="{esc(str(ctype))}"'
    if drip is not None:
        attrs += f' data-drip-days="{drip}"'

    lock_head, lock_note = "", ""
    if gated:
        lock_head = f'<span class="lock-glyph-wrap">{LOCK_SVG}</span>'
        parts = []
        if locked:
            cond = m.get("unlock_condition") or "Locked"
            parts.append(f'<span data-unlock-condition>{esc(cond)}</span>')
        if drip is not None:
            fb = f"unlocks {drip} day{'s' if drip != 1 else ''} after enrollment"
            parts.append(f'<span class="drip-note" data-drip-note data-drip-days="{drip}" '
                         f'data-lesson="{lid}" data-fallback="{esc(fb)}">{esc(fb)}</span>')
        lock_note = '<div class="lock-note">' + " ".join(parts) + "</div>"

    btn = f'<button class="complete-btn" data-lesson="{lid}"'
    if gated:
        btn += " disabled"
    btn += ">Mark complete</button>"

    action = ""
    if m.get("funnel"):
        fcfg = m["funnel"]
        action = ('<div class="action-card" data-funnel="1">'
                  '<p class="action-teaser">This lesson is an action step — '
                  'take the action to move forward.</p>'
                  f'<a class="cta-btn" href="{esc(fcfg["url"])}" '
                  f'target="_blank" rel="noopener">{esc(fcfg["label"])}</a>'
                  "</div>")

    mats = ""
    if m.get("materials"):
        chips = []
        for mat in m["materials"]:
            chips.append(
                f'<a class="chip" data-mat-type="{esc(mat["type"])}" '
                f'href="{esc(mat["url"])}" download>{material_icon(mat["type"])}'
                f'<span class="chip-title">{esc(mat["title"])}</span>'
                f'<span class="chip-type">{esc(mat["type"])}</span></a>')
        mats = '<div class="materials"><h3>Materials</h3>' + "".join(chips) + "</div>"

    discuss = ""
    cs = m.get("comment_status", "visible")
    if cs == "visible":
        discuss = ('<div class="discuss" data-discuss="visible">'
                   '<span class="discuss-title">Discuss this lesson</span>'
                   '<span class="discuss-note">Discussion happens outside this '
                   'package — this static course site has no comment backend.</span></div>')
    elif cs == "locked":
        discuss = ('<div class="discuss" data-discuss="locked">'
                   '<span class="discuss-title">' + LOCK_SVG +
                   ' Discussion is locked</span>'
                   '<span class="discuss-note">Comments are disabled for this '
                   'lesson by the course policy.</span></div>')
    # hidden: no discuss affordance at all

    return f"""
<section class="lesson" id="{lid}" data-lesson="{lid}" data-xp="{xp}" {attrs}>
  <div class="lesson-head">
    <h2>{i}. {esc(lesson["title"])}</h2>
    <span class="meta">{dur} · {lesson["segments"]} segments · +{xp} XP</span>
    {lock_head}
    {btn}
  </div>
  {lock_note}
  {action}
  <div class="insights">
    <h3>Insights</h3>
    <ul class="insight-list">{bullets}</ul>
    {seed_html}
    <div class="tags">{kws} {cons}</div>
  </div>
  {mats}
  {discuss}
  <details class="full-text"><summary>Full transcript</summary>
    <div class="lesson-body" contenteditable="true">{esc(lesson["text"])}</div>
  </details>
</section>"""


def build_course_map_toc(lessons, meta_by_lesson, esc):
    """Interactive course-map TOC (dossier §5.1): per-lesson checkboxes that
    persist into the SAME consumer-progress-v1 store, per-category integer %
    progress, lock glyphs for gated lessons. Draft lessons are excluded."""
    cats, order = {}, []
    for lesson in lessons:
        m = meta_by_lesson[lesson["id"]] or {}
        if m.get("visibility", "published") == "draft":
            continue
        ck = m.get("category") or "_uncategorized"
        ct = m.get("category_title") or "Lessons"
        if ck not in cats:
            cats[ck] = {"title": ct, "lessons": []}
            order.append(ck)
        cats[ck]["lessons"].append((lesson, m))
    parts = []
    for ck in order:
        cat = cats[ck]
        lis = []
        for lesson, m in cat["lessons"]:
            lid = lesson["id"]
            vis = m.get("visibility", "published")
            drip = m.get("drip_days")
            gated = vis == "locked" or drip is not None
            lockbits = ""
            if gated:
                bits = []
                if vis == "locked":
                    cond = m.get("unlock_condition") or "Locked"
                    bits.append(f'<span data-unlock-text>{esc(cond)}</span>')
                if drip is not None:
                    fb = f"unlocks {drip} day{'s' if drip != 1 else ''} after enrollment"
                    bits.append(f'<span class="drip-note" data-drip-note '
                                f'data-drip-days="{drip}" data-lesson="{lid}" '
                                f'data-fallback="{esc(fb)}">{esc(fb)}</span>')
                lockbits = ('<span class="cmap-lock">' + LOCK_SVG
                            + "".join(bits) + "</span>")
            lis.append(
                f'<li class="cmap-lesson" data-cmap-lesson="{lid}" data-visibility="{vis}">'
                f'<input type="checkbox" class="cmap-check" data-lesson="{lid}"'
                + (" disabled" if gated else "")
                + f' aria-label="Mark {esc(lesson["title"])} complete">'
                f'<a href="#{lid}">{esc(lesson["title"])}</a>{lockbits}</li>')
        parts.append(
            f'<div class="cmap-cat" data-cmap-cat="{esc(ck)}">'
            f'<div class="cmap-cat-head"><span class="cmap-cat-title">{esc(cat["title"])}</span>'
            f'<span class="cmap-cat-progress" data-cmap-progress="{esc(ck)}">0%</span></div>'
            f'<ul class="cmap-lessons">' + "".join(lis) + "</ul></div>")
    return ('<nav id="course-map-toc" aria-label="Course map">\n'
            "  <h2>Course map</h2>\n  " + "\n  ".join(parts) + "\n</nav>\n")


def build_certificate_section(title, esc):
    """Printable certificate (dossier §5.9): unlocks at 100% completion;
    learner name via a localStorage-backed prompt; print CSS, no backend."""
    return f"""
<section id="certificate" data-cert-locked="true">
  <div class="cert-locked" data-cert-locked-note>Complete all lessons to unlock your certificate — <span id="cert-progress-inline">0%</span> complete.</div>
  <div class="cert-body" data-cert-body hidden>
    <div class="cert-frame">
      <h2>Certificate of Completion</h2>
      <p class="cert-course">{esc(title)}</p>
      <p class="cert-award">This certifies that</p>
      <p class="cert-name" id="cert-name" contenteditable="true" spellcheck="false">Learner</p>
      <p class="cert-award">has completed every lesson of this course.</p>
      <p class="cert-meta"><span id="cert-date"></span> · {esc(title)}</p>
    </div>
    <div class="cert-actions">
      <button id="cert-edit-name" class="ghost-btn" type="button">Change name</button>
      <button id="cert-print" class="complete-btn" type="button">Print certificate</button>
    </div>
  </div>
</section>"""


META_CSS = """/* course-map metadata features (gated: absent on legacy corpora) */
#course-map-toc { background: var(--panel); border: 1px solid rgba(128,128,128,.18); border-radius: 14px; padding: 1rem 1.2rem; margin: 1.2rem 0; }
#course-map-toc h2 { margin: 0 0 .6rem; font-size: 1rem; }
.cmap-cat + .cmap-cat { margin-top: .9rem; }
.cmap-cat-head { display: flex; justify-content: space-between; align-items: baseline; gap: .6rem; }
.cmap-cat-title { font-weight: 600; font-size: .9rem; }
.cmap-cat-progress { color: var(--xp); font-size: .8rem; font-variant-numeric: tabular-nums; }
.cmap-lessons { list-style: none; margin: .3rem 0 0; padding: 0; }
.cmap-lesson { display: flex; align-items: center; gap: .5rem; padding: .25rem 0; font-size: .88rem; }
.cmap-lesson a { color: var(--ink); text-decoration: none; flex: 1; }
.cmap-lesson a:hover { text-decoration: underline; }
.cmap-lesson.locked a { color: var(--muted); }
.cmap-lesson:not(.locked) .cmap-lock { display: none; }
.cmap-check { accent-color: var(--xp); flex-shrink: 0; }
.cmap-lock { color: var(--muted); display: inline-flex; align-items: center; gap: .3rem; font-size: .75rem; }
.toc-lock { display: inline-flex; margin-left: .3rem; color: var(--muted); }
.lock-glyph-wrap { display: none; color: var(--muted); align-items: center; }
.lesson[data-visibility="locked"] .lock-glyph-wrap, .lesson.is-locked .lock-glyph-wrap { display: inline-flex; }
.lock-note { display: none; margin-top: .5rem; font-size: .85rem; color: var(--muted); background: rgba(128,128,128,.08); border-radius: 8px; padding: .45rem .7rem; gap: .5rem; }
.lesson[data-visibility="locked"] .lock-note, .lesson.is-locked .lock-note { display: block; }
.lesson.is-locked .insights, .lesson.is-locked details.full-text, .lesson.is-locked .action-card, .lesson.is-locked .materials { opacity: .45; }
.action-card { margin: .8rem 0; padding: 1.1rem 1.2rem; border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); border-radius: 12px; background: color-mix(in srgb, var(--accent) 12%, transparent); text-align: center; }
.action-teaser { margin: 0 0 .7rem; color: var(--muted); font-size: .85rem; }
.cta-btn { display: inline-block; background: var(--accent); color: #fff; font-weight: 700; padding: .7rem 1.6rem; border-radius: 10px; text-decoration: none; font-size: 1rem; box-shadow: 0 4px 18px rgba(0,0,0,.25); }
.cta-btn:hover { filter: brightness(1.1); }
.materials { margin-top: .8rem; }
.materials h3 { margin: 0 0 .4rem; font-size: .8rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.chip { display: inline-flex; align-items: center; gap: .4rem; background: rgba(128,128,128,.12); border: 1px solid rgba(128,128,128,.25); border-radius: 999px; padding: .3rem .8rem .3rem .6rem; margin: .2rem .35rem .2rem 0; font-size: .8rem; color: var(--ink); text-decoration: none; }
.chip:hover { border-color: var(--accent); }
.chip-type { color: var(--muted); font-size: .7rem; text-transform: uppercase; }
.discuss { margin-top: .8rem; font-size: .85rem; color: var(--muted); border-top: 1px dashed rgba(128,128,128,.25); padding-top: .6rem; }
.discuss-title { font-weight: 600; color: var(--ink); display: inline-flex; align-items: center; gap: .35rem; }
.discuss-note { display: block; margin-top: .15rem; }
#course-progress-label { font-variant-numeric: tabular-nums; }
#certificate { margin: 1.5rem 0; }
.cert-locked { background: rgba(128,128,128,.08); border: 1px dashed rgba(128,128,128,.35); border-radius: 12px; padding: .9rem 1.1rem; color: var(--muted); font-size: .9rem; }
.cert-frame { border: 3px double color-mix(in srgb, var(--xp) 60%, transparent); border-radius: 4px; padding: 2.2rem 1.6rem; text-align: center; background: var(--panel); }
.cert-frame h2 { margin: 0 0 .3rem; letter-spacing: .12em; text-transform: uppercase; font-size: 1.1rem; }
.cert-course { color: var(--muted); margin: .2rem 0 1.2rem; }
.cert-award { margin: .4rem 0; color: var(--muted); font-size: .9rem; }
.cert-name { font-size: 1.8rem; font-weight: 700; margin: .5rem 0; border-bottom: 1px solid rgba(128,128,128,.4); display: inline-block; padding: 0 1.5rem .3rem; outline: none; }
.cert-meta { margin-top: 1.4rem; font-size: .8rem; color: var(--muted); }
.cert-actions { margin-top: .8rem; display: flex; gap: .6rem; justify-content: center; }
.ghost-btn { background: transparent; border: 1px solid rgba(128,128,128,.4); color: var(--ink); padding: .35rem .8rem; border-radius: 8px; cursor: pointer; font-size: .8rem; }
@media print {
  body > *:not(main) { display: none !important; }
  main > *:not(#certificate) { display: none !important; }
  #certificate { display: block !important; }
  #certificate .cert-locked, #certificate .cert-actions { display: none !important; }
  #certificate .cert-body { display: block !important; }
  body { background: #fff; color: #000; }
}"""

# Client-side drip + progress model (dossier §5.3/§5.5). One source of truth:
# the same consumer-progress-v1 store the XP hook reads — % and XP are both
# derived from s.done, so they can never diverge.
META_JS_CORE = """const CMAP_PUB = CMAP.filter(function (l) { return l.visibility !== "draft"; });
(function () {  // enrollment date = first visit (client-side drip)
  var s = state();
  if (!s.enrolled_at) { s.enrolled_at = Date.now(); save(s); }
})();
function daysLeft(dripDays) {
  var s = state();
  var unlockAt = (s.enrolled_at || Date.now()) + dripDays * 86400000;
  return Math.max(0, Math.ceil((unlockAt - Date.now()) / 86400000));
}
function lessonLocked(l) {
  if (l.visibility === "locked") return true;
  return l.drip_days != null && daysLeft(l.drip_days) > 0;
}
function lockText(l) {
  if (l.drip_days != null) {
    var dl = daysLeft(l.drip_days);
    if (dl > 0) return "unlocks in " + dl + (dl === 1 ? " day" : " days");
  }
  return null;
}
function courseProgress() {
  var s = state();
  var completed = 0, cats = {};
  CMAP_PUB.forEach(function (l) {
    var done = !!s.done[l.id];
    if (done) completed++;
    var ck = l.category || "lessons";
    if (!cats[ck]) cats[ck] = { total: 0, completed: 0 };
    cats[ck].total++;
    if (done) cats[ck].completed++;
  });
  return {
    progress: CMAP_PUB.length ? Math.round(completed / CMAP_PUB.length * 100) : 0,
    completedLessons: completed,
    totalLessons: CMAP_PUB.length,
    categories: Object.keys(cats).map(function (k) {
      return { id: k, progress: cats[k].total ? Math.round(cats[k].completed / cats[k].total * 100) : 0 };
    }),
  };
}
function updateCertificate(cp) {
  var sec = document.getElementById("certificate");
  if (!sec) return;
  var s = state();
  var unlocked = cp.totalLessons > 0 && cp.progress >= 100;
  sec.dataset.certLocked = unlocked ? "false" : "true";
  var note = sec.querySelector("[data-cert-locked-note]");
  var body = sec.querySelector("[data-cert-body]");
  var inline = document.getElementById("cert-progress-inline");
  if (inline) inline.textContent = cp.progress + "%";
  if (note) note.hidden = unlocked;
  if (body) body.hidden = !unlocked;
  if (unlocked) {
    var name = s.learner_name;
    if (!name) {
      name = (window.prompt("Your name for the certificate:") || "").trim() || "Learner";
      var s2 = state(); s2.learner_name = name; save(s2); s.learner_name = name;
    }
    var nameEl = document.getElementById("cert-name");
    if (nameEl && nameEl.textContent !== name) nameEl.textContent = name;
    if (!s.cert_issued_at) {
      var s3 = state(); s3.cert_issued_at = Date.now(); save(s3);
      s.cert_issued_at = s3.cert_issued_at;
    }
    var dEl = document.getElementById("cert-date");
    if (dEl) dEl.textContent = new Date(s.cert_issued_at || Date.now()).toLocaleDateString();
  }
}"""

META_REFRESH_JS = """  if (typeof CMAP !== "undefined") {
    var cp = courseProgress();
    var cpl = document.getElementById("course-progress-label");
    if (cpl) cpl.textContent = cp.completedLessons + "/" + cp.totalLessons + " · " + cp.progress + "%";
    CMAP.forEach(function (l) {
      var locked = lessonLocked(l);
      var lt = lockText(l);
      var sec = document.querySelector('.lesson[data-lesson="' + l.id + '"]');
      if (sec) {
        sec.classList.toggle("is-locked", locked);
        var btn = sec.querySelector(".complete-btn");
        if (btn) btn.disabled = locked;
      }
      document.querySelectorAll('.drip-note[data-lesson="' + l.id + '"]').forEach(function (el) {
        el.textContent = lt || el.dataset.fallback || el.textContent;
      });
      var chk = document.querySelector('.cmap-check[data-lesson="' + l.id + '"]');
      if (chk) {
        chk.checked = !!s.done[l.id];
        chk.disabled = locked;
        var row = chk.closest(".cmap-lesson");
        if (row) row.classList.toggle("locked", locked);
      }
    });
    cp.categories.forEach(function (c) {
      document.querySelectorAll('[data-cmap-progress="' + c.id + '"]').forEach(function (el) {
        el.textContent = c.progress + "%";
      });
    });
    updateCertificate(cp);
  }"""

META_POST_JS = """if (typeof CMAP !== "undefined") {
  // course-map TOC checkboxes write to the SAME consumer-progress-v1 store
  // the Mark-complete buttons and the XP hook use — one source of truth.
  document.querySelectorAll(".cmap-check").forEach(function (chk) {
    chk.addEventListener("change", function () {
      var s = state();
      var id = chk.dataset.lesson;
      if (chk.checked) { s.done[id] = Date.now(); } else { delete s.done[id]; }
      save(s); refresh();
      if (s.done[id]) {
        var sec = document.querySelector('.lesson[data-lesson="' + id + '"]');
        if (sec) toast("+" + sec.dataset.xp + " XP");
      }
    });
  });
  var certPrint = document.getElementById("cert-print");
  if (certPrint) certPrint.addEventListener("click", function () { window.print(); });
  var certName = document.getElementById("cert-name");
  if (certName) certName.addEventListener("input", function () {
    var s = state(); s.learner_name = certName.textContent; save(s);
  });
  var certEdit = document.getElementById("cert-edit-name");
  if (certEdit) certEdit.addEventListener("click", function () {
    var name = (window.prompt("Your name for the certificate:", state().learner_name || "") || "").trim();
    if (name) { var s = state(); s.learner_name = name; save(s); refresh(); }
  });
}"""


def build_site(title, course_map_md, keywords, concepts, seeds, lessons, brand,
               meta=None):
    esc = html_mod.escape
    kw_json = json.dumps(keywords[:80])
    seeds_json = json.dumps(seeds[:40])
    concepts_json = json.dumps(concepts[:60])

    # ---- course-map metadata (None -> legacy output, byte-identical) ----
    mkey = _mkey
    meta_by_lesson = {}
    for lesson in lessons:
        m = (meta or {}).get("lesson_meta", {}).get(mkey(lesson["title"]))
        meta_by_lesson[lesson["id"]] = m or None

    has_meta = meta is not None
    # ordered (lesson_id, meta) rows; category order: first-appearance of each
    # lesson's category key, then None-category lessons; the flat legacy
    # (no-meta) path never builds these structures
    if has_meta:
        cat_order = []
        for lesson in lessons:
            m = meta_by_lesson[lesson["id"]]
            ck = (m or {}).get("category")
            if ck is not None and ck not in cat_order:
                cat_order.append(ck)
        cmap_lessons_js = []
        for lesson in lessons:
            m = meta_by_lesson[lesson["id"]] or {}
            cmap_lessons_js.append({
                "id": lesson["id"], "title": lesson["title"],
                "visibility": m.get("visibility", "published"),
                "contentType": m.get("content_type"),
                "category": m.get("category"),
                "drip_days": m.get("drip_days"),
                "comment_status": m.get("comment_status", "visible"),
            })
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
        if has_meta:
            m = meta_by_lesson[lid]
            if (m or {}).get("visibility", "published") == "draft":
                toc_items.pop()  # draft: hidden from nav, unlinked
            else:
                toc_items[-1] = meta_toc_item(i, lesson, m, esc)
            lesson_html.append(render_meta_lesson(
                i, lesson, m, ins, xp, dur, bullets, kws, cons, seed_html, esc))
        else:
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
    # ---- meta slot values (all empty on the legacy path: byte-identical) ----
    meta_css = META_CSS + "\n" if has_meta else ""
    meta_cmap_js = ("const CMAP = " + json.dumps(cmap_lessons_js) + ";\n"
                    if has_meta else "")
    meta_js_core = META_JS_CORE + "\n" if has_meta else ""
    meta_refresh_js = META_REFRESH_JS if has_meta else ""
    meta_post_js = META_POST_JS + "\n" if has_meta else ""
    meta_cmap_toc = (build_course_map_toc(lessons, meta_by_lesson, esc)
                     if has_meta else "")
    meta_cert = build_certificate_section(title, esc) + "\n" if has_meta else ""
    meta_progress_label = (' <span id="course-progress-label" '
                           'aria-label="course progress">0/0 · 0%</span>'
                           if has_meta else "")
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
{meta_css}</style>
</head>
<body>
<header>
  <h1>{esc(title)}</h1>
  <div id="xp-bar">
    <span id="xp-label">0 / {xp_total} XP</span>
    <div id="xp-fill"><i id="xp-prog"></i></div>
    <span id="level-label">Level 1</span>{meta_progress_label}
  </div>
  <button id="export-btn" title="Export your edited lessons as a new edition">Export edition</button>
  <button id="train-btn" title="Package this course as a training package">Training package</button>
</header>
<button id="toc-toggle">☰ Contents</button>
<nav id="toc"><ul style="list-style:none;padding:0;margin:0">{toc}</ul></nav>
<main>
<section id="course-map" style="white-space:pre-wrap">{esc(course_map_md)}</section>
{meta_css}{meta_cmap_toc}{"".join(lesson_html)}
{meta_cert}</main>
<div id="toast"></div>
<script>
const LESSONS = {lessons_js};
const INSIGHTS = {insight_js};
const KW = {kw_json};
{meta_cmap_js}{meta_js_core}const KEY = "consumer-progress-v1";

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
{meta_refresh_js}}}

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

{meta_post_js}refresh();
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
    ap.add_argument("--course-map-json", default=None,
                    help="explicit course-map.json path (default: auto-detect "
                         "course-map.json in or beside the distilled dir)")
    ap.add_argument("--no-offer", action="store_true",
                    help="do not emit offer.json (only sites WITH course-map "
                         "metadata emit one)")
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

    # optional course-map metadata (gates every new surface; legacy corpora
    # -> meta is None -> byte-identical legacy output)
    cmap_raw = None
    for cand in ([a.course_map_json] if a.course_map_json else []) + [
            os.path.join(d, "course-map.json"),
            os.path.join(d, "..", "course-map.json")]:
        if cand and os.path.exists(cand):
            cmap_raw = load_json(cand, None)
            if cmap_raw is not None:
                break
    meta = norm_course_map(cmap_raw, a.title, lessons) if cmap_raw else None

    brand = ("dark" if a.brand == "dark" else "light") == "dark" and {
        "bg": "#0e0f13", "panel": "#16181f", "ink": "#e8eaf0", "accent": "#7c5cff",
        "muted": "#8b90a0", "xp": "#38d39f"} or {
        "bg": "#f7f8fa", "panel": "#ffffff", "ink": "#17181d", "accent": "#5b45d6",
        "muted": "#6b7280", "xp": "#0e9f6e"}

    site = build_site(a.title, course_map, keywords, concepts, seeds, lessons, brand,
                      meta=meta)
    out = a.out or os.path.join(d, "site", "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(site)
    result = {"ok": True, "out": os.path.abspath(out), "lessons": len(lessons),
              "bytes": len(site)}
    # offer != course (dossier §5.4): offer.json is emitted BESIDE the site,
    # derived from the metadata layer — never baked into the content HTML.
    if meta and not a.no_offer:
        offer_path = os.path.join(os.path.dirname(out), "offer.json")
        with open(offer_path, "w") as f:
            json.dump(meta["offer"], f, indent=2)
        result["offer"] = os.path.abspath(offer_path)
    if meta:
        result["course_map_schema"] = meta["schema"]
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