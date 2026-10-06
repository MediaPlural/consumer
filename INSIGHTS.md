# The `{AgentName} Insights` Convention

> One pattern across every MediaPlural surface — and every adopter's surface:
> **AI summary + insights, always one tap away, on any relevant page/screen.**

Named per the surface's AI: **Viiy Insights**, **Tails Insights**, **Foxy
Insights**, `{YourAgent} Insights`. Same panel, same data contract, same
behavior — only the name changes.

## The law (product-wide)

1. **Every content surface gets the tap.** Documents, emails, lessons,
   transcripts, thread views, dashboards — if a screen shows content a human
   is about to read, it has an Insights affordance.
2. **One tap, never blocking.** The panel opens over the content; the content
   is never navigated away from. Close = exactly where you were.
3. **Offline-first.** The panel always works with the local extractive
   engine (zero backend). LLM-grade output is an upgrade button, not a
   prerequisite.
4. **Same data contract everywhere:**
   - `summary[]` — 3–5 bullets, thesis-first
   - `keywords[]` — top terms as chips
   - `concepts[]` — named multi-word concepts as chips
   - `next_best` — the one high-signal sentence (feeds the next-best-sentence
     engine: marketing copy, reply drafts, lesson openers)
5. **Provenance visible.** The panel shows what it read (source element) and
   which engine produced the insight (local extractive vs agent-grade).

## Implementation

`insights.js` is the reference widget — dependency-free, dark/light, any
agent name:

```html
<script src="insights.js"></script>
<script>
  // whole document:
  Insights.mountAll({ agentName: "Viiy" });

  // specific surfaces (email body, a lesson, a doc):
  Insights.mount({ agentName: "Tails", target: "#email-body" });
</script>
```

Or mark surfaces declaratively:

```html
<article data-insights data-insights-agent="Foxy"> ... </article>
```

- `data-insights` — mount a panel for this element
- `data-insights-agent="Name"` — the panel's brand (default: "Viiy")
- `data-insights-placement="bottom-left|bottom-right"` — button side

## Engine seam

- **Local (default):** `Insights.extractiveInsights(text)` — the same
  algorithm as the consumer distiller (keyword density + position scoring,
  bigram concepts, next-best extraction). No network.
- **Agent-grade (optional):** pass `mcpUrl` to `mount()`: the panel grows a
  "Deeper (agent-grade)" button that calls your endpoint with
  `{ text, want: "insights" }` and expects the same data contract back.
  The consumer MCP server is the reference backend.

## In this repo

- `sitegen.py` renders per-lesson Insights inline (the course surface).
- `insights.js` is the drop-in for everything else (documents, emails,
  threads, any DOM surface).
- The extractive algorithm is intentionally identical across
  `distill.py`, `sitegen.py`, and `insights.js` — one doctrine, three hosts.