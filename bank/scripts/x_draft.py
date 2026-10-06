#!/usr/bin/env python3
"""X (x.com) act-lane helper — DRAFT ONLY, by design.

The 'x' connector is status needs-auth: posting to X requires API OAuth
with the write scope, which is NOT configured on this box. There is no
scraping bypass and no auto-post: this script only writes a draft file
for a human to review and post manually. Never add network calls here
until a real OAuth lane exists (and even then, posting stays human-gated).
"""
import argparse
import datetime
import os
import sys


def main():
    p = argparse.ArgumentParser(description="Write an X post draft (never posts)")
    p.add_argument("--text", required=True, help="draft post text")
    p.add_argument("--out-dir", default=os.path.expanduser("~/.consumer/x-drafts"))
    a = p.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(a.out_dir, f"draft-{ts}.md")
    with open(path, "w") as f:
        f.write(a.text.rstrip() + "\n")
    n = len(a.text)
    warn = " (OVER 280 chars — will not fit a standard post)" if n > 280 else ""
    print(f"draft written: {path} ({n} chars){warn}")
    print("status: needs-auth — X API OAuth (write scope) not configured. "
          "Human gate: review the draft and post it manually.")
    return 0


if __name__ == "__main__":
    sys.exit(main())