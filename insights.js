/* consumer insights.js — "{AgentName} Insights", always a tap away.
 *
 * Drop-in, dependency-free widget: any element (document body, email, lesson,
 * article) gets a floating "✦ {Name} Insights" button that opens a panel with
 * an AI summary (bullets), keywords, concepts, and a next-best-sentence.
 *
 * Offline-first: ships an extractive summarizer (same algorithm as the
 * consumer distiller) so it works with zero backend. If `mcpUrl` is set, the
 * panel calls the consumer MCP server's `distill` tool for LLM-grade output.
 *
 * Usage:
 *   <script src="insights.js"></script>
 *   <script> Insights.mountAll({ agentName: "Viiy" }); </script>
 * or target one surface:
 *   Insights.mount({ agentName: "Tails", target: "#email-body" });
 *
 * Data contract (panel sections, in order):
 *   summary[]      — 3-5 bullets, thesis-first
 *   keywords[]     — top terms, chips
 *   concepts[]     — named multi-word concepts, chips
 *   next_best      — one high-signal sentence (the "seed")
 */
(function (global) {
  "use strict";

  var DEFAULTS = {
    agentName: "Viiy",          // the rename surface: "Viiy Insights", "Tails Insights"...
    placement: "bottom-right",  // floating button position
    theme: "dark",
    maxBullets: 5,
    mcpUrl: null,               // optional: consumer MCP endpoint for LLM-grade insights
    labelText: null,            // defaults to "✦ {agentName} Insights"
  };

  var STOP = new Map([["the",1],["and",1],["for",1],["that",1],["with",1],["this",1],
    ["are",1],["was",1],["were",1],["have",1],["has",1],["had",1],["will",1],["your",1],
    ["you",1],["from",1],["they",1],["them",1],["their",1],["then",1],["than",1],["into",1],
    ["just",1],["like",1],["what",1],["when",1],["where",1],["which",1],["who",1],["how",1],
    ["all",1],["any",1],["can",1],["did",1],["does",1],["done",1],["get",1],["got",1],
    ["its",1],["it's",1],["not",1],["but",1],["out",1],["about",1],["because",1],["been",1],
    ["being",1],["also",1],["more",1],["most",1],["some",1],["such",1],["only",1],["own",1],
    ["same",1],["very",1],["way",1],["okay",1],["yeah",1],["um",1],["make",1],["makes",1]]);

  function tokenize(text) {
    return (text.toLowerCase().match(/[a-z][a-z'-]{2,}/g) || []);
  }

  /* ---- extractive insights (offline core; mirrors distill.py) ---- */
  function extractiveInsights(text, opts) {
    var sentences = (text.match(/[^.!?]+[.!?]+/g) || [])
      .map(function (s) { return s.trim(); })
      .filter(function (s) { return s.length > 25; });
    if (!sentences.length) return { summary: [], keywords: [], concepts: [], next_best: null };

    // keyword scoring: tf x length-bonus
    var tf = new Map();
    tokenize(text).forEach(function (w) {
      if (STOP.has(w)) return;
      tf.set(w, (tf.get(w) || 0) + 1);
    });
    var keywords = Array.from(tf.entries())
      .map(function (e) { return { term: e[0], score: e[1] * (0.5 + Math.min(e[0].length, 10) / 10) }; })
      .sort(function (a, b) { return b.score - a.score; })
      .slice(0, 14)
      .map(function (k) { return k.term; });

    // concepts: frequent content bigrams
    var bigrams = new Map();
    var words = tokenize(text);
    for (var i = 0; i < words.length - 1; i++) {
      var w1 = words[i], w2 = words[i + 1];
      if (STOP.has(w1) || STOP.has(w2) || w1 === w2) continue;
      var bg = w1 + " " + w2;
      bigrams.set(bg, (bigrams.get(bg) || 0) + 1);
    }
    var concepts = Array.from(bigrams.entries())
      .filter(function (e) { return e[1] >= 2; })
      .sort(function (a, b) { return b[1] - a[1]; })
      .slice(0, 8).map(function (e) { return e[0]; });

    // summary: keyword-density + early-position scoring, deduped
    var kwSet = new Set(keywords.slice(0, 40));
    var scored = sentences.map(function (s, idx) {
      var toks = tokenize(s);
      var dens = toks.length ? toks.reduce(function (a, w) { return a + (kwSet.has(w) ? 1 : 0); }, 0) / toks.length : 0;
      return { s: s, idx: idx, score: dens + (idx < 3 ? 1.0 : 0) };
    }).sort(function (a, b) { return b.score - a.score || a.idx - b.idx; });

    var picked = [], seen = new Set();
    for (var j = 0; j < scored.length && picked.length < (opts.maxBullets || 5); j++) {
      var sig = Array.from(new Set((scored[j].s.toLowerCase().match(/[a-z]{4,}/g) || []))).sort().slice(0, 8).join(" ");
      if (seen.has(sig)) continue;
      seen.add(sig);
      picked.push({ s: scored[j].s, idx: scored[j].idx });
    }
    picked.sort(function (a, b) { return a.idx - b.idx; });

    // next-best: top-scoring sentence NOT already in the summary
    var nextBest = null;
    var summarySet = new Set(picked.map(function (p) { return p.s; }));
    for (var k = 0; k < scored.length; k++) {
      if (!summarySet.has(scored[k].s)) { nextBest = scored[k].s; break; }
    }

    return {
      summary: picked.map(function (p) { return p.s; }),
      keywords: keywords,
      concepts: concepts,
      next_best: nextBest,
    };
  }

  /* ---- optional MCP upgrade path ---- */
  function mcpInsights(text, mcpUrl) {
    // consumer MCP: tools/call distill on a temp corpus is heavy; the panel
    // uses the local engine by default and this hook is the upgrade seam.
    return fetch(mcpUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text, want: "insights" }),
    }).then(function (r) { return r.json(); });
  }

  /* ---- panel ---- */
  function buildPanel(host, opts, insights, sourceEl) {
    var label = opts.labelText || ("✦ " + opts.agentName + " Insights");
    var dark = opts.theme !== "light";
    var css = "position:fixed;" + (opts.placement === "bottom-left" ? "left:18px;bottom:18px;" : "right:18px;bottom:18px;");
    var btn = document.createElement("button");
    btn.className = "insights-fab";
    btn.textContent = label;
    btn.setAttribute("aria-label", opts.agentName + " Insights");
    btn.style.cssText = css + "z-index:99990;border:none;border-radius:999px;padding:.6rem 1.1rem;" +
      "cursor:pointer;font-weight:600;font-size:.85rem;box-shadow:0 4px 18px rgba(0,0,0,.35);" +
      "background:" + (dark ? "#7c5cff" : "#5b45d6") + ";color:#fff;";
    var panel = document.createElement("aside");
    panel.className = "insights-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", opts.agentName + " Insights panel");
    panel.style.cssText = "position:fixed;" + (opts.placement === "bottom-left" ? "left:18px;" : "right:18px;") +
      "bottom:74px;width:min(360px, calc(100vw - 36px));max-height:60vh;overflow:auto;z-index:99989;" +
      "border-radius:14px;padding:1rem 1.2rem;display:none;" +
      "background:" + (dark ? "#16181f" : "#ffffff") + ";color:" + (dark ? "#e8eaf0" : "#17181d") + ";" +
      "border:1px solid " + (dark ? "rgba(128,128,128,.3)" : "rgba(23,24,29,.15)") + ";" +
      "box-shadow:0 10px 40px rgba(0,0,0,.4);";
    host.appendChild(btn);
    host.appendChild(panel);

    function chip(t, kind) {
      var s = document.createElement("span");
      s.textContent = t;
      s.style.cssText = "display:inline-block;font-size:.7rem;padding:.12rem .55rem;border-radius:999px;" +
        "margin:.15rem .15rem 0 0;background:" + (kind === "kw"
          ? (dark ? "rgba(124,92,255,.25)" : "rgba(91,69,214,.15)")
          : (dark ? "rgba(56,211,159,.25)" : "rgba(14,159,110,.15)")) + ";";
      return s;
    }

    function render(data) {
      // Security note: innerHTML is used ONLY to clear (""), never to inject;
      // all content below is built with textContent — untrusted course/email
      // text cannot XSS through this panel.
      panel.innerHTML = "";
      var h = document.createElement("h3");
      h.textContent = label;
      h.style.cssText = "margin:0 0 .5rem;font-size:.95rem;";
      panel.appendChild(h);
      var ul = document.createElement("ul");
      ul.style.cssText = "margin:0;padding-left:1.1rem;";
      (data.summary || []).forEach(function (b) {
        var li = document.createElement("li");
        li.textContent = b;
        li.style.marginBottom = ".3rem";
        ul.appendChild(li);
      });
      if (ul.children.length) panel.appendChild(ul);
      var tags = document.createElement("div");
      tags.style.marginTop = ".5rem";
      (data.keywords || []).forEach(function (k) { tags.appendChild(chip(k, "kw")); });
      (data.concepts || []).forEach(function (c) { tags.appendChild(chip(c, "cpt")); });
      if (tags.children.length) panel.appendChild(tags);
      if (data.next_best) {
        var nb = document.createElement("div");
        nb.innerHTML = "";
        var em = document.createElement("em");
        em.textContent = data.next_best;
        var lead = document.createElement("span");
        lead.textContent = "Next-best: ";
        lead.style.cssText = "color:" + (dark ? "#8b90a0" : "#6b7280") + ";font-size:.8rem;";
        nb.appendChild(lead); nb.appendChild(em);
        nb.style.cssText = "margin-top:.6rem;font-size:.85rem;";
        panel.appendChild(nb);
      }
      if (opts.mcpUrl) {
        var up = document.createElement("button");
        up.textContent = "✨ Deeper (agent-grade)";
        up.style.cssText = "margin-top:.7rem;background:transparent;border:1px solid " +
          (dark ? "#7c5cff" : "#5b45d6") + ";color:" + (dark ? "#7c5cff" : "#5b45d6") +
          ";padding:.3rem .7rem;border-radius:8px;cursor:pointer;font-size:.75rem;";
        up.onclick = function () {
          up.textContent = "…thinking";
          mcpInsights(sourceEl.innerText, opts.mcpUrl).then(function (r) {
            if (r && r.summary) { render(r); } else { up.textContent = "(no upgrade available)"; }
          }).catch(function () { up.textContent = "(offline — using local engine)"; });
        };
        panel.appendChild(up);
      }
    }

    var dirty = true;
    btn.onclick = function () {
      var open = panel.style.display === "block";
      panel.style.display = open ? "none" : "block";
      if (!open && dirty) {
        render(extractiveInsights(sourceEl.innerText || sourceEl.textContent || "", opts));
        dirty = false;
      }
    };
    return { btn: btn, panel: panel, render: render };
  }

  function mount(opts) {
    opts = Object.assign({}, DEFAULTS, opts || {});
    var target = typeof opts.target === "string" ? document.querySelector(opts.target) : (opts.target || document.body);
    if (!target) return null;
    return buildPanel(document.body, opts, null, target);
  }

  function mountAll(opts) {
    opts = Object.assign({}, DEFAULTS, opts || {});
    var out = [];
    // every element marked data-insights gets its own panel
    document.querySelectorAll("[data-insights]").forEach(function (el) {
      out.push(buildPanel(document.body, Object.assign({}, opts, {
        agentName: el.getAttribute("data-insights-agent") || opts.agentName,
        placement: el.getAttribute("data-insights-placement") || opts.placement,
      }), null, el));
    });
    // no marked surfaces: one panel for the whole document
    if (!out.length) out.push(mount(opts));
    return out;
  }

  global.Insights = { mount: mount, mountAll: mountAll, extractiveInsights: extractiveInsights };
})(typeof window !== "undefined" ? window : globalThis);