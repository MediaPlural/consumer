---
name: consumer
version: 0.3.0
description: |
  Use when consuming ANY knowledge material into a structured, attributed,
  queryable knowledge graph, or creating courses/training sites FROM consumed
  knowledge. The knowledge consumer: acquire, transcribe (local STT), ingest
  any format, graph, query, author, explain. Local-first, stdlib-only,
  provenance-anchored.
user-invocable: true
---

# Consumer (OpenClaw)

Same engine, OpenClaw dialect. Full manual: ../SKILL.md (the universal body).

Quick path:

1. Resolve CONSUMER_HOME (../SKILL.md "Locate the engine").
2. Invoke via shell: `python3 $CONSUMER_HOME/source.py <target> --full`
3. Query: `python3 $CONSUMER_HOME/graph.py search "<q>"`

Slash command: `/consumer` (user-invocable). MCP lane (optional): add the
consumer-mcp stdio server via `openclaw mcp add consumer-mcp --command python3
--arg $CONSUMER_HOME/mcp-server.py` then `openclaw mcp doctor consumer-mcp
--probe`.

Laws: local custody (creds in ~/.consumer/creds/<platform>/, never in argv or
logs), attribution inbuilt, no DRM breaking, SAFE runner for bank actions.
