#!/usr/bin/env bash
# consumer install-skill — make the pipeline loadable as a Hermes skill.
# Usage: bash install-skill.sh [target-skills-dir]
# Default target: ~/.hermes/skills (the default profile's skill dir).
# Any skill-dir-shaped target works (e.g. ~/.hermes/shared-skills for
# fleet-wide visibility across profiles).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-$HOME/.hermes/skills}"
DEST="$TARGET/consumer"

say() { printf '[install-skill] %s\n' "$*"; }

if [ ! -f "$HERE/skills/consumer/SKILL.md" ]; then
  say "FATAL: skills/consumer/SKILL.md not found in repo"; exit 1
fi

mkdir -p "$TARGET"
if [ -e "$DEST" ]; then
  rm -rf "$DEST"
  say "replaced existing $DEST"
fi
cp -R "$HERE/skills/consumer" "$DEST"
say "installed skill -> $DEST"

# the skill body references the repo; embed the resolved path so sessions
# find the tools regardless of cwd
printf '\n<!-- resolved repo path: %s -->\n' "$HERE" >> "$DEST/SKILL.md"
say "repo path pinned: $HERE"

say "verify (new or existing session):"
say "  skill_view(name='consumer')"
say "  python3 $HERE/tests/test_smoke.py   # 22/22 expected"